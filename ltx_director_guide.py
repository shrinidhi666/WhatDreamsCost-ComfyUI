import logging
import math
import os
import av
import numpy as np
import torch
import comfy
import comfy.sd
import comfy.utils
import folder_paths
import node_helpers
from comfy_extras import nodes_lt
from comfy_api.latest import io
from .ltx_director import GuideData, MotionGuideData, _resize_image

log = logging.getLogger(__name__)

# --- Helper Functions from Nghtdrp ---

def _get_guide_attention_entries(conditioning):
    for item in conditioning:
        entries = item[1].get("guide_attention_entries", None)
        if entries is not None:
            return entries
    return []

def _set_guide_attention_entries(conditioning, entries):
    return node_helpers.conditioning_set_values(
        conditioning, {"guide_attention_entries": entries}
    )

def _append_guide_attention_entry(
    conditioning,
    pre_filter_count,
    latent_shape,
    attention_strength=1.0,
    attention_mask=None,
):
    entries = [*_get_guide_attention_entries(conditioning)]
    entries.append(
        {
            "pre_filter_count": int(pre_filter_count),
            "strength": float(attention_strength),
            "pixel_mask": attention_mask,
            "latent_shape": list(latent_shape),
        }
    )
    return _set_guide_attention_entries(conditioning, entries)

def _clone_noise_mask(latent, latent_image):
    if "noise_mask" in latent and latent["noise_mask"] is not None:
        return latent["noise_mask"].clone()
    batch, _, frames, _, _ = latent_image.shape
    return torch.ones(
        (batch, 1, frames, 1, 1),
        dtype=torch.float32,
        device=latent_image.device,
    )

def _resize_latent_spatial(latent_image, noise_mask, width, height, method):
    b, c, f, h, w = latent_image.shape
    if width == w and height == h:
        return latent_image, noise_mask

    latent_4d = latent_image.permute(0, 2, 1, 3, 4).reshape(b * f, c, h, w)
    latent_4d = comfy.utils.common_upscale(latent_4d, width, height, method, "disabled")
    latent_image = latent_4d.reshape(b, f, c, height, width).permute(0, 2, 1, 3, 4)

    if noise_mask is not None and (noise_mask.shape[-1] > 1 or noise_mask.shape[-2] > 1):
        mb, mc, mf, mh, mw = noise_mask.shape
        mask_4d = noise_mask.permute(0, 2, 1, 3, 4).reshape(mb * mf, mc, mh, mw)
        mask_4d = comfy.utils.common_upscale(mask_4d, width, height, method, "disabled")
        noise_mask = mask_4d.reshape(mb, mf, mc, height, width).permute(0, 2, 1, 3, 4)

    return latent_image, noise_mask

def _ceil_to_multiple(value, multiple):
    multiple = max(1, int(multiple))
    return int(math.ceil(value / multiple) * multiple)

def _snap_latent_to_downscale(latent_image, noise_mask, downscale_factor, method):
    factor = int(max(1, round(float(downscale_factor))))
    if factor <= 1:
        return latent_image, noise_mask

    _, _, _, h, w = latent_image.shape
    new_w = _ceil_to_multiple(w, factor)
    new_h = _ceil_to_multiple(h, factor)
    if new_w == w and new_h == h:
        return latent_image, noise_mask

    log.warning(
        "[LTXDirectorGuide] Auto-snapping latent grid from %sx%s to %sx%s for IC-LoRA downscale factor %s.",
        w, h, new_w, new_h, factor,
    )
    return _resize_latent_spatial(latent_image, noise_mask, new_w, new_h, method)

def _load_lora_model_only(model, ic_lora_name, strength_model):
    lora_path = folder_paths.get_full_path_or_raise("loras", ic_lora_name)
    lora, metadata = comfy.utils.load_torch_file(
        lora_path, safe_load=True, return_metadata=True,
    )

    try:
        latent_downscale_factor = float(metadata["reference_downscale_factor"])
    except Exception:
        latent_downscale_factor = 1.0
        log.warning(
            "[LTXDirectorGuide] Could not read reference_downscale_factor from %s, using 1.0.",
            ic_lora_name,
        )

    if strength_model == 0:
        return model, latent_downscale_factor

    model_lora, _ = comfy.sd.load_lora_for_models(
        model, None, lora, strength_model, 0,
    )
    return model_lora, latent_downscale_factor

def _encode_video_iclora_guide(vae, latent_width, latent_height, images, scale_factors, latent_downscale_factor, crop, use_tiled_encode, tile_size, tile_overlap, resize_method="crop"):
    time_scale_factor, width_scale_factor, height_scale_factor = scale_factors

    num_frames_to_keep = ((images.shape[0] - 1) // time_scale_factor) * time_scale_factor + 1
    images = images[:num_frames_to_keep]

    target_width = int(latent_width * width_scale_factor / latent_downscale_factor)
    target_height = int(latent_height * height_scale_factor / latent_downscale_factor)
    target_width = max(8, target_width)
    target_height = max(8, target_height)

    # For guides, we must match the exact target latent shape.
    # "maintain aspect ratio" doesn't pad, which causes shape mismatch in VAE encode / concatenation.
    # So we fallback "maintain aspect ratio" to "pad".
    if resize_method == "maintain aspect ratio":
        resize_method = "pad"

    pixels = _resize_image(images, target_width, target_height, resize_method, divisible_by=1)

    encode_pixels = pixels[:, :, :, :3]
    if use_tiled_encode:
        guide_latent = vae.encode_tiled(encode_pixels, tile_x=tile_size, tile_y=tile_size, overlap=tile_overlap)
    else:
        guide_latent = vae.encode(encode_pixels)

    return pixels, guide_latent

def _dilate_latent(latent: dict, horizontal_scale: int, vertical_scale: int) -> dict:
    if horizontal_scale == 1 and vertical_scale == 1:
        return latent

    samples = latent["samples"]
    mask = latent.get("noise_mask", None)

    dilated_shape = samples.shape[:3] + (
        samples.shape[3] * vertical_scale,
        samples.shape[4] * horizontal_scale,
    )
    dilated_samples = torch.zeros(dilated_shape, device=samples.device, dtype=samples.dtype, requires_grad=False)
    dilated_samples[..., ::vertical_scale, ::horizontal_scale] = samples

    dilated_mask_shape = (
        dilated_samples.shape[0], 1, dilated_samples.shape[2],
        dilated_samples.shape[3], dilated_samples.shape[4],
    )
    dilated_mask = torch.full(dilated_mask_shape, -1.0, device=samples.device, dtype=samples.dtype, requires_grad=False)
    dilated_mask[..., ::vertical_scale, ::horizontal_scale] = (mask if mask is not None else 1.0)
    
    return {"samples": dilated_samples, "noise_mask": dilated_mask}

# --- MSR (Multi-Subject Reference) compositor ---
# Ported from ComfyUI-Licon-MSR (LiconMSR.create_video) so the Director has no hard dependency
# on that pack. Reference behavior preserved: each still is stretch-fitted to the target size
# (LiconMSR uses cv2 LANCZOS4; _resize_image's lanczos matches) and the frame budget is split
# evenly across subjects + background, remainder distributed from the front.

def _expand_msr_frames(images, frame_count):
    base_count = frame_count // len(images)
    remainder = frame_count % len(images)
    frames = []
    for index, image in enumerate(images):
        repeats = base_count + (1 if index < remainder else 0)
        frames.extend([image] * repeats)
    return frames

def _load_msr_panel_image(image_file):
    from PIL import Image
    file_path = os.path.join(folder_paths.get_input_directory(), image_file)
    if not os.path.exists(file_path):
        raise ValueError(f"[LTXDirectorGuide] MSR panel image not found in the input folder: {image_file}")
    img = Image.open(file_path).convert("RGB")
    arr = np.array(img, dtype=np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)

def _load_msr_panel(tdata, default_frame_count):
    """Read the Director's MSR panel out of timeline_data (subjects/background uploaded to the
    ComfyUI input folder by the JS panel) — the single source for MSR references. Missing files
    raise: a silent black reference would quietly destroy the identity lock."""
    panel = tdata.get("msr") or {}
    subject_files = [f for f in (panel.get("subjects") or []) if f]
    background_file = panel.get("background") or ""
    if not subject_files and not background_file:
        return [], None, default_frame_count
    if not subject_files or not background_file:
        raise ValueError("[LTXDirectorGuide] MSR panel: at least one subject AND a background are required.")
    subjects = [_load_msr_panel_image(f) for f in subject_files[:4]]
    background = _load_msr_panel_image(background_file)
    try:
        frame_count = int(panel.get("frameCount", default_frame_count) or default_frame_count)
    except (TypeError, ValueError):
        frame_count = default_frame_count
    if frame_count not in (17, 25, 33, 41):
        frame_count = default_frame_count
    return subjects, background, frame_count

def _build_msr_guide(subjects, background, width, height, frame_count, resize_method="stretch to fit"):
    """Compose the MSR reference clip: 1-4 subject stills + a background still, each resized to
    width x height, expanded to frame_count frames. Returns [frame_count, H, W, 3] float32.
    `resize_method` fits each reference to the target: "stretch to fit" is LiconMSR's own
    behavior (cv2.resize -- distorts on aspect mismatch); "crop" center-crops to fill (no
    distortion, matches the official sample's crop=center); "pad"/"pad green" letterbox.
    Every method yields exactly width x height so the frames stack."""
    if resize_method == "maintain aspect ratio":
        resize_method = "pad"  # must end exactly WxH to stack; no-pad fitting cannot
    prepared = []
    for img in [*subjects, background]:
        t = img[:1] if img.ndim == 4 else img.unsqueeze(0)
        t = t[..., :3].float()
        t = _resize_image(t, width, height, resize_method, 1, "lanczos")
        prepared.append(t[0])
    frames = _expand_msr_frames(prepared, int(frame_count))
    return torch.stack(frames, dim=0)

def _resolve_input_video_path(video_file):
    if os.path.isabs(str(video_file)) and os.path.exists(str(video_file)):
        return str(video_file)
    input_dir = folder_paths.get_input_directory()
    candidate = os.path.join(input_dir, str(video_file))
    if os.path.exists(candidate):
        return candidate
    try:
        annotated = folder_paths.get_annotated_filepath(str(video_file))
        if annotated and os.path.exists(annotated):
            return annotated
    except Exception:
        pass
    raise FileNotFoundError(f"Could not find motion guide video: {video_file}")

class ResampleGuideFrames:
    def execute(self, images, source_fps, target_fps, target_num_frames, mode):
        if images is None: return images
        frames = images
        n = int(frames.shape[0])
        target_num_frames = int(target_num_frames)
        if n <= 1:
            if target_num_frames > 1 and n == 1:
                return frames.repeat(target_num_frames, 1, 1, 1)
            return frames
        source_fps = float(max(0.001, source_fps))
        target_fps = float(max(0.001, target_fps))
        if target_num_frames <= 0:
            duration = (n - 1) / source_fps
            target_num_frames = max(1, int(round(duration * target_fps)) + 1)
        if target_num_frames == n and abs(target_fps - source_fps) < 1e-6:
            return frames
        positions = torch.linspace(0, n - 1, target_num_frames, device=frames.device, dtype=torch.float32)
        if mode == "nearest":
            idx = torch.round(positions).long().clamp(0, n - 1)
            return frames.index_select(0, idx)
        idx0 = torch.floor(positions).long().clamp(0, n - 1)
        idx1 = torch.ceil(positions).long().clamp(0, n - 1)
        alpha = (positions - idx0.to(positions.dtype)).view(-1, 1, 1, 1)
        f0 = frames.index_select(0, idx0).to(torch.float32)
        f1 = frames.index_select(0, idx1).to(torch.float32)
        return (f0 * (1.0 - alpha) + f1 * alpha).to(frames.dtype)

def _load_motion_video_frames(video_file, trim_start_frames, length_frames, director_fps, resample_mode="nearest"):
    path = _resolve_input_video_path(video_file)
    target_fps = max(1.0, float(director_fps))
    start_s = max(0.0, float(trim_start_frames) / target_fps)
    dur_s = max(0.0, float(length_frames) / target_fps)
    end_s = start_s + dur_s if dur_s > 0 else None

    log.info(f"[LTXDirectorGuide] Loading video frames from {path}. start_s: {start_s:.3f}, dur_s: {dur_s:.3f}, end_s: {end_s}")

    container = av.open(path)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"  # Enable multi-threaded decoding

    try:
        source_fps = float(stream.average_rate) if stream.average_rate else float(stream.base_rate)
    except Exception:
        source_fps = target_fps
    if source_fps <= 0: source_fps = target_fps

    # Seek to keyframe slightly before target start_s to optimize loading speed and memory
    if start_s > 0:
        try:
            if stream.time_base:
                seek_pts = int(max(0, start_s - 0.5) / float(stream.time_base))
            else:
                seek_pts = int(max(0, start_s - 0.5) * av.time_base)
            container.seek(seek_pts, stream=stream, backward=True)
            log.info(f"[LTXDirectorGuide] PyAV seeked stream to pts={seek_pts} (approx {max(0, start_s - 0.5):.3f}s)")
        except Exception as seek_err:
            log.warning(f"[LTXDirectorGuide] Seek failed: {seek_err}, decoding from beginning.")

    frames = []
    decoded_count = 0
    for frame in container.decode(stream):
        if frame.time is not None:
            t = float(frame.time)
        elif frame.pts is not None and stream.time_base is not None:
            t = float(frame.pts * stream.time_base)
        else:
            t = float(decoded_count / source_fps)
        decoded_count += 1

        if t < start_s - 0.01: continue
        if end_s is not None and t >= end_s: break
        
        # Append raw uint8 numpy arrays to minimize CPU allocation overhead
        frames.append(frame.to_ndarray(format="rgb24"))
    container.close()

    if not frames: raise ValueError(f"No frames decoded for motion guide segment: {video_file}")
    
    # Convert all frames to float32 at once to optimize memory allocation
    frames_np = np.array(frames, dtype=np.float32) / 255.0
    images = torch.from_numpy(frames_np)

    target_count = max(1, int(round(float(length_frames))))
    images = ResampleGuideFrames().execute(images, source_fps, target_fps, target_count, resample_mode)
    return images

# --- Main Class ---

class LTXDirectorGuide:
    @classmethod
    def INPUT_TYPES(cls):
        loras = folder_paths.get_filename_list("loras")
        if not loras: loras = ["put_ic_lora_in_ComfyUI_models_loras"]
        return {
            "required": {
                "positive": ("CONDITIONING", {"tooltip": "Positive conditioning to add guide keyframe info to."}),
                "negative": ("CONDITIONING", {"tooltip": "Negative conditioning to add guide keyframe info to."}),
                "vae": ("VAE", {"tooltip": "Video VAE used to encode the guide images."}),
                "latent": ("LATENT", {"tooltip": "Video latent — guides are inserted into this latent."}),
                "guide_data": ("GUIDE_DATA", {"tooltip": "Guide data produced by Prompt Relay Encode (Timeline)."}),
            },
            "optional": {
                "motion_guide_data": ("MOTION_GUIDE_DATA", {"tooltip": "Connect motion guide data from the timeline node to use IC-LoRA video guidance."}),
                "model": ("MODEL", {"tooltip": "Connect model if using IC-LoRA for motion guidance."}),
                "ic_lora_name": (["None"] + loras, {"default": "None", "tooltip": "Select the IC-LoRA model to use for motion guidance."}),
                "ic_lora_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                "image_resize_method": (["lanczos", "bicubic", "area", "bilinear", "nearest-exact", "bislerp"], {"default": "lanczos", "tooltip": "Resampling filter used to resize the RAW guide images to this stage's resolution. lanczos = highest quality for up- and down-scaling."}),
                "resize_method": (["maintain aspect ratio", "stretch to fit", "pad", "pad green", "crop"], {"default": "maintain aspect ratio", "tooltip": "How the raw guide images are fitted to the target resolution. Also used as the motion / IC-LoRA fit method."}),
                "image_width": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 32, "tooltip": "Resolution (WIDTH) the guide image is fed into LTXVPreprocess at. 0 = native full-res (highest quality). Set BOTH image_width and image_height for an exact resolution (like ImageResizeKJv2). The image is resized to the latent grid afterward for encoding."}),
                "image_height": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 32, "tooltip": "Resolution (HEIGHT) the guide image is fed into LTXVPreprocess at. 0 = native full-res (highest quality). Set BOTH image_width and image_height for an exact resolution (like ImageResizeKJv2). The image is resized to the latent grid afterward for encoding."}),
                "img_compression": ("INT", {"default": 18, "min": 0, "max": 100, "step": 1, "tooltip": "CRF preprocess (LTXVPreprocess) applied to the guide image at THIS stage. 0 = none. This is the only place compression happens — set per stage (e.g. 22 for the prepass, 18 for the upscale)."}),
                "image_attention_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Master guide-attention strength for image keyframes. Each keyframe's own Guide Strength (set per segment in the Director timeline) MULTIPLIES this, giving true per-image weighting on the attention rail."}),
                "crop": (["disabled", "center"], {"default": "center"}),
                "auto_snap_ic_grid": ("BOOLEAN", {"default": True}),
                "use_tiled_encode": ("BOOLEAN", {"default": False}),
                "tile_size": ("INT", {"default": 256, "min": 64, "max": 512, "step": 32}),
                "tile_overlap": ("INT", {"default": 64, "min": 16, "max": 256, "step": 16}),
                "retake_mode": ("BOOLEAN", {"default": False, "tooltip": "Force Retake Mode. If false, it will still auto-detect Retake Mode from the timeline data."}),
                "msr_lora_name": (["None"] + loras, {"default": "None", "tooltip": "Licon-MSR (multi-subject reference) IC-LoRA. Chained on top of ic_lora_name and applied ONLY when MSR references are set on the Director's MSR panel."}),
                "msr_lora_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                "msr_attention_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Guide-attention strength for the MSR reference tokens."}),
                "msr_resize_method": (["crop", "stretch to fit", "pad", "pad green"], {"default": "crop", "tooltip": "How each MSR reference is fitted to the video's aspect. crop = center-crop, no distortion (the official sample's behavior; best for refs of mixed aspect ratios). stretch to fit = LiconMSR's own behavior, distorts on aspect mismatch. pad / pad green = letterbox."}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT", "MODEL", "FLOAT")
    RETURN_NAMES = ("positive", "negative", "latent", "model", "latent_downscale_factor")
    FUNCTION = "execute"

    @classmethod
    def execute(cls, positive, negative, vae, latent, guide_data, motion_guide_data=None, model=None, ic_lora_name="None", ic_lora_strength=1.0, image_resize_method="lanczos", resize_method="maintain aspect ratio", image_width=0, image_height=0, img_compression=18, image_attention_strength=1.0, crop="center", auto_snap_ic_grid=True, use_tiled_encode=False, tile_size=256, tile_overlap=64, retake_mode=False, msr_lora_name="None", msr_lora_strength=1.0, msr_attention_strength=1.0, msr_resize_method="crop"):
        motion_segments = (motion_guide_data or {}).get("segments", []) if motion_guide_data else []
        image_guides_count = len(guide_data.get("images", [])) if guide_data else 0
        print(f"[LTXDirectorGuide] execute started. motion_segments: {len(motion_segments)}, image_guides: {image_guides_count}, ic_lora_name: {ic_lora_name}, model connected: {model is not None}, retake_mode: {retake_mode}")

        # Fit method for both the image guides and the motion / IC-LoRA path comes from this
        # node's own resize_method widget (the Director no longer dictates it).
        active_resize_method = resize_method

        # Parse timeline JSON early: retake detection and track contents decide which LoRAs load.
        import json
        timeline_data_str = guide_data.get("timeline_data", "{}") if guide_data else "{}"
        try:
            tdata = json.loads(timeline_data_str)
        except Exception:
            tdata = {}
        is_retake_active = bool(retake_mode) or tdata.get("retakeMode", False)

        # Director image guides and motion video segments
        images = guide_data.get("images", []) if guide_data else []
        insert_frames = guide_data.get("insert_frames", []) if guide_data else []
        strengths = guide_data.get("strengths", []) if guide_data else []
        segments = (motion_guide_data or {}).get("segments", [])

        # MSR track: subjects + background + frame count come from the Director's MSR panel
        # (timeline_data.msr) — the single source for MSR references.
        msr_subjects, msr_background, msr_frame_count = _load_msr_panel(tdata, 17)
        msr_active = msr_background is not None and len(msr_subjects) > 0
        if msr_active and is_retake_active:
            log.warning("[LTXDirectorGuide] MSR inputs are ignored in Retake Mode.")
            msr_active = False

        # Track-gated LoRA loading: each LoRA is applied ONLY when its track has content, so an
        # unused track never patches the model. Both can chain (control first, identity second).
        timeline_used = len(images) > 0 or len(segments) > 0 or is_retake_active
        latent_downscale_factor = 1.0
        ic_lora_applied = False
        if model is not None and ic_lora_name != "None" and timeline_used:
            model, latent_downscale_factor = _load_lora_model_only(model, ic_lora_name, ic_lora_strength)
            ic_lora_applied = True
        elif ic_lora_name != "None":
            log.info("[LTXDirectorGuide] ic_lora '%s' not applied (no timeline guides or no model connected).", ic_lora_name)

        msr_downscale_factor = 1.0
        msr_lora_applied = False
        if model is not None and msr_lora_name != "None" and msr_active:
            model, msr_downscale_factor = _load_lora_model_only(model, msr_lora_name, msr_lora_strength)
            msr_lora_applied = True
        elif msr_lora_name != "None" and not msr_active:
            log.info("[LTXDirectorGuide] msr_lora '%s' not applied (no MSR references on the Director panel).", msr_lora_name)
        if msr_active and not msr_lora_applied:
            log.warning(
                "[LTXDirectorGuide] MSR references are set on the Director panel but no MSR LoRA "
                "is applied here (msr_lora_name is None or no model connected). The MSR guide only "
                "works with the MSR IC-LoRA active — chain it upstream or set msr_lora_name."
            )

        scale_factors = vae.downscale_index_formula
        latent_image = latent["samples"].clone()
        noise_mask = _clone_noise_mask(latent, latent_image)

        # The latent is NEVER resized here. Its size (= the video resolution) comes only from
        # the Director's empty latent (pass 1) and the LTXVLatentUpsampler (pass 2). The guide
        # just reads the latent and encodes guides into it.

        # IC-LoRA correctness only: snap the latent grid to the IC-LoRA downscale factor so the
        # reference encoding aligns. Not user scaling — runs solely when an IC-LoRA is active.
        if auto_snap_ic_grid and ic_lora_applied:
            latent_image, noise_mask = _snap_latent_to_downscale(latent_image, noise_mask, latent_downscale_factor, "bicubic")

        _, _, latent_length, latent_height, latent_width = latent_image.shape
        initial_latent_length = int(latent_length)

        is_empty_latent = (latent_image.abs().max().item() < 1e-5)

        director_fps = float((motion_guide_data or {}).get("frame_rate", guide_data.get("frame_rate", 24) if guide_data else 24))

        is_lora_active = ic_lora_applied or msr_lora_applied
        time_scale_factor = scale_factors[0]
        ltxv_length = (latent_length - 1) * time_scale_factor + 1

        # -----------------------------------------------------------------------
        # Retake Mode Branch:
        # Load single base video, encode continuously, apply temporal mask.
        # -----------------------------------------------------------------------
        if is_retake_active:
            print(f"[LTXDirectorGuide] Retake Mode active. Preserving base latent, masking selected regions. is_empty_latent: {is_empty_latent}")
            target_width = latent_width * 32
            target_height = latent_height * 32

            # Calculate retake region latent indices first so we know what to copy/paste
            retake_start = int(tdata.get("retakeStart", 0))
            retake_len = int(tdata.get("retakeLength", 0))
            retake_strength = float(tdata.get("retakeStrength", 1.0))

            start_frame = int(guide_data.get("start_frame", 0))
            relative_start = max(0, retake_start - start_frame)
            
            l_start = relative_start // time_scale_factor
            l_end = int(math.ceil((relative_start + retake_len) / time_scale_factor))
            
            l_start = min(l_start, latent_length)
            l_end = min(l_end, latent_length)

            # Stage 2 optimization: If the retake region covers the entire generation area,
            # there are no preserved regions to copy over in Stage 2. We can bypass video loading/encoding.
            need_base_video = True
            if not is_empty_latent and l_start == 0 and l_end >= latent_length:
                need_base_video = False
                print("[LTXDirectorGuide] Stage 2: Retake region covers the entire generated range. Skipping base video loading and VAE encoding.")

            # 1. Try to load and encode base video from timeline data
            retake_vid_info = tdata.get("retakeVideo") or {}
            video_file = retake_vid_info.get("imageFile", "") if isinstance(retake_vid_info, dict) else ""
            
            # Fallback to first segment only if it exists and we have no retake video info at all (old workflows)
            if not video_file and not retake_vid_info and len(segments) > 0:
                video_file = segments[0].get("videoFile", "")

            if need_base_video:
                if not video_file:
                    if retake_vid_info and not retake_vid_info.get("imageFile"):
                        raise ValueError(
                            "Retake Mode is active, but the base video file upload is still in progress (or failed). "
                            "Please wait for the 'Uploading base video...' overlay on the timeline to disappear before queuing the prompt."
                        )
                    else:
                        raise ValueError(
                            "Retake Mode is active, but no base video has been selected on the timeline. "
                            "Please drag and drop or upload a base video on the timeline first."
                        )

            if video_file and need_base_video:
                try:
                    print(f"[LTXDirectorGuide] Loading and encoding base video file: {video_file} starting at frame {start_frame} for length {ltxv_length} at resolution {target_width}x{target_height}")
                    video_frames = _load_motion_video_frames(
                        video_file, trim_start_frames=start_frame, length_frames=ltxv_length, director_fps=director_fps, resample_mode="nearest"
                    )

                    # Retake base video must match the exact target latent shape.
                    # "maintain aspect ratio" doesn't pad, which causes shape mismatch in VAE encode.
                    # So we fallback "maintain aspect ratio" to "pad" for retake base video.
                    retake_resize_method = active_resize_method
                    if retake_resize_method == "maintain aspect ratio":
                        retake_resize_method = "pad"

                    pixels = _resize_image(video_frames, target_width, target_height, retake_resize_method, divisible_by=1)

                    num_clip_frames = pixels.shape[0]
                    num_frames_to_keep = ((num_clip_frames - 1) // time_scale_factor) * time_scale_factor + 1
                    encode_src = pixels[:num_frames_to_keep, :, :, :3]

                    if use_tiled_encode:
                        base_latent = vae.encode_tiled(encode_src, tile_x=tile_size, tile_y=tile_size, overlap=tile_overlap)
                    else:
                        base_latent = vae.encode(encode_src)
                    
                    base_latent = base_latent.to(device=latent_image.device, dtype=latent_image.dtype)
                    
                    # Copy to latent_image
                    paste_len = min(base_latent.shape[2], latent_length)
                    if is_empty_latent:
                        # Stage 1: Overwrite entire latent with base video VAE encode
                        latent_image[:, :, :paste_len] = base_latent[:, :, :paste_len]
                    else:
                        # Stage 2: Overwrite only preserved regions (before l_start and after l_end)
                        # leaving the generated retake region from Stage 1 untouched
                        print(f"[LTXDirectorGuide] Stage 2: Copying high-resolution base latent for preserved regions (0-{l_start} and {l_end}-{paste_len})")
                        if l_start > 0:
                            latent_image[:, :, :l_start] = base_latent[:, :, :l_start]
                        if l_end < paste_len:
                            latent_image[:, :, l_end:paste_len] = base_latent[:, :, l_end:paste_len]
                except Exception as e:
                    print(f"[LTXDirectorGuide] Failed to load/encode base video: {e}. Falling back to input latent.")

            # 2. Build the temporal noise mask (0.0 = frozen, 1.0 = regenerate)
            noise_mask = torch.zeros_like(noise_mask) # Initialize fully frozen
            
            l_start = min(l_start, latent_length)
            l_end = min(l_end, latent_length)

            if l_end > l_start:
                noise_mask[:, :, l_start:l_end] = retake_strength

            print(f"[LTXDirectorGuide] noise_mask slice: {noise_mask[0, 0, :, 0, 0].tolist()}")

            # In retake mode, skip normal mode processing entirely and return immediately!
            exact_crop_frames = max(0, int(latent_image.shape[2]) - initial_latent_length)
            positive = node_helpers.conditioning_set_values(positive, {"nghtdrp_guide_crop_latent_frames": exact_crop_frames})
            negative = node_helpers.conditioning_set_values(negative, {"nghtdrp_guide_crop_latent_frames": exact_crop_frames})
            return (positive, negative, {"samples": latent_image, "noise_mask": noise_mask}, model, float(latent_downscale_factor))

        # -----------------------------------------------------------------------
        # Standard Timeline Keyframe Guidance:
        # Appends image segments as keyframes (and motion segments if present)
        # to the latent stream using standard LTX-Video cross-attention conditioning.
        # Registers guide attention entries if IC-LoRA is active.
        # -----------------------------------------------------------------------
        if len(images) > 0 or len(segments) > 0 or msr_active:
            print(f"[LTXDirectorGuide] Using Appended Keyframe Guidance. is_lora_active: {is_lora_active}, msr_active: {msr_active}")

            target_pix_w = int(latent_width * 32)
            target_pix_h = int(latent_height * 32)

            # A0. MSR reference clip — composed subjects + background, injected at frame 0 with
            # strength 1.0 and the MSR LoRA's own downscale factor, matching the official
            # Licon-MSR sample (LTXAddVideoICLoRAGuide frame_idx=0, strength=1, factor=1).
            if msr_active:
                msr_frames = _build_msr_guide(msr_subjects, msr_background, target_pix_w, target_pix_h, msr_frame_count, resize_method=msr_resize_method)
                _, msr_guide_latent = _encode_video_iclora_guide(
                    vae, latent_width, latent_height, msr_frames, scale_factors,
                    msr_downscale_factor, crop, use_tiled_encode, tile_size, tile_overlap,
                    resize_method=active_resize_method,
                )
                if msr_guide_latent.shape[2] > latent_length:
                    msr_guide_latent = msr_guide_latent[:, :, :latent_length]
                msr_guide_shape = list(msr_guide_latent.shape[2:])

                B_g, _, F_g, H_g, W_g = msr_guide_latent.shape
                msr_guide_mask = torch.ones((B_g, 1, F_g, H_g, W_g), device=msr_guide_latent.device, dtype=msr_guide_latent.dtype)
                msr_ldf = int(max(1, round(float(msr_downscale_factor))))
                if msr_ldf > 1:
                    dilated = _dilate_latent({"samples": msr_guide_latent, "noise_mask": msr_guide_mask}, horizontal_scale=msr_ldf, vertical_scale=msr_ldf)
                    msr_guide_mask = dilated["noise_mask"]
                    msr_guide_latent = dilated["samples"]

                tokens_added = msr_guide_latent.shape[2] * msr_guide_latent.shape[3] * msr_guide_latent.shape[4]
                positive, negative, latent_image, noise_mask = nodes_lt.LTXVAddGuide.append_keyframe(
                    positive, negative, 0, latent_image, noise_mask, msr_guide_latent, 1.0, scale_factors,
                    guide_mask=msr_guide_mask, latent_downscale_factor=float(msr_downscale_factor), causal_fix=True,
                )
                if is_lora_active:
                    positive = _append_guide_attention_entry(positive, tokens_added, msr_guide_shape, attention_strength=msr_attention_strength)
                    negative = _append_guide_attention_entry(negative, tokens_added, msr_guide_shape, attention_strength=msr_attention_strength)
                print(f"[LTXDirectorGuide] MSR guide injected: {len(msr_subjects)} subject(s) + background, {int(msr_frame_count)} frames -> latent {msr_guide_shape} at frame 0.")

            # A. Process Image Guides — images arrive RAW from the Director. Resize them to
            # THIS stage's resolution and compress here (the only place compression happens).
            for idx, img_tensor in enumerate(images):
                f_idx = insert_frames[idx] if idx < len(insert_frames) else 0
                strength = float(strengths[idx] if idx < len(strengths) else 1.0)
                if strength <= 0.0:
                    continue

                src = img_tensor  # RAW image from the Director (full-res, un-compressed)

                # 1. Resolution fed into LTXVPreprocess. image_width/image_height both > 0 =
                #    exact resolution (like ImageResizeKJv2); 0 = native full-res (no pre-resize).
                if image_width > 0 and image_height > 0:
                    src = _resize_image(src, image_width, image_height, active_resize_method, 32, image_resize_method)

                # 2. LTXV preprocess (compression) runs at THAT resolution — the only place
                #    compression happens, per stage.
                if img_compression > 0:
                    src = nodes_lt.LTXVPreprocess().execute(src, img_compression)[0]

                # 3. Bring the compressed image to the latent grid for the VAE encode so the
                #    guide latent aligns with the video latent (_resize_image is a no-op when
                #    already that size).
                src = _resize_image(src, target_pix_w, target_pix_h, active_resize_method, 32, image_resize_method)

                img_tensor = src

                image_pixels, guide_latent = nodes_lt.LTXVAddGuide.encode(vae, latent_width, latent_height, img_tensor, scale_factors)
                frame_idx, latent_idx = nodes_lt.LTXVAddGuide.get_latent_index(positive, latent_length, len(image_pixels), int(f_idx), scale_factors)

                if latent_idx >= latent_length:
                    continue

                max_frames = latent_length - latent_idx
                if guide_latent.shape[2] > max_frames:
                    guide_latent = guide_latent[:, :, :max_frames]

                tokens_added = guide_latent.shape[2] * guide_latent.shape[3] * guide_latent.shape[4]
                guide_orig_shape = list(guide_latent.shape[2:])

                positive, negative, latent_image, noise_mask = nodes_lt.LTXVAddGuide.append_keyframe(
                    positive, negative, frame_idx, latent_image, noise_mask, guide_latent, strength, scale_factors
                )
                if is_lora_active:
                    # Per-image strength on the channel that actually steers in LTX 2.3: the
                    # noise mask above is the weak channel (keyframe tokens are always injected
                    # at full presence), so the segment's Guide Strength also scales THIS image's
                    # attention entry -- image_attention_strength stays the master fader
                    # (defaults 1.0 x 1.0 = previous behavior). Mirrors the motion track's
                    # per-segment videoAttentionStrength.
                    positive = _append_guide_attention_entry(positive, tokens_added, guide_orig_shape, attention_strength=image_attention_strength * strength)
                    negative = _append_guide_attention_entry(negative, tokens_added, guide_orig_shape, attention_strength=image_attention_strength * strength)

            # B. Process Motion Video Segments
            for seg in segments:
                try:
                    video_file = seg.get("videoFile")
                    if not video_file:
                        continue

                    start_frame = int(seg.get("start", 0))
                    length_frames = int(seg.get("length", 1))
                    trim_start = int(seg.get("trimStart", 0))
                    video_strength = float(seg.get("videoStrength", 1.0))
                    video_attention_strength = float(seg.get("videoAttentionStrength", 0.65))

                    if length_frames <= 0 or video_strength <= 0.0:
                        continue

                    start_frame_aligned = start_frame
                    video_frames = _load_motion_video_frames(video_file, trim_start, length_frames, director_fps, seg.get("resampleMode", "nearest"))

                    num_frames_to_keep = ((video_frames.shape[0] - 1) // time_scale_factor) * time_scale_factor + 1
                    video_frames = video_frames[:num_frames_to_keep]
                    causal_fix = int(start_frame_aligned) == 0 or num_frames_to_keep == 1
                    encode_frames = video_frames if causal_fix else torch.cat([video_frames[:1], video_frames], dim=0)

                    _, guide_latent = _encode_video_iclora_guide(vae, latent_width, latent_height, encode_frames, scale_factors, latent_downscale_factor, crop, use_tiled_encode, tile_size, tile_overlap, resize_method=active_resize_method)

                    if not causal_fix:
                        guide_latent = guide_latent[:, :, 1:, :, :]

                    frame_idx = start_frame_aligned
                    latent_idx = (frame_idx + time_scale_factor - 1) // time_scale_factor if frame_idx > 0 else 0

                    if latent_idx >= latent_length:
                        continue

                    if start_frame > 0 and guide_latent.shape[2] > 1:
                        guide_latent = guide_latent[:, :, 1:, :, :]
                        frame_idx += time_scale_factor
                        latent_idx += 1
                        if latent_idx >= latent_length:
                            continue

                    max_frames = latent_length - latent_idx
                    if guide_latent.shape[2] > max_frames:
                        guide_latent = guide_latent[:, :, :max_frames]

                    guide_orig_shape = list(guide_latent.shape[2:])

                    B_g, C_g, F_g, H_g, W_g = guide_latent.shape
                    guide_mask = torch.ones((B_g, 1, F_g, H_g, W_g), device=guide_latent.device, dtype=guide_latent.dtype)

                    if start_frame > 0:
                        ramp_steps = [0.25, 0.65]
                        for i, s in enumerate(ramp_steps):
                            if i < F_g:
                                guide_mask_val = 1.0 + video_strength * (1.0 - s)
                                guide_mask[:, :, i, :, :] = guide_mask_val

                    ldf = int(max(1, round(float(latent_downscale_factor))))
                    if ldf > 1:
                        dilated = _dilate_latent({"samples": guide_latent, "noise_mask": guide_mask}, horizontal_scale=ldf, vertical_scale=ldf)
                        guide_mask = dilated["noise_mask"]
                        guide_latent = dilated["samples"]

                    tokens_added = guide_latent.shape[2] * guide_latent.shape[3] * guide_latent.shape[4]
                    positive, negative, latent_image, noise_mask = nodes_lt.LTXVAddGuide.append_keyframe(
                        positive, negative, frame_idx, latent_image, noise_mask, guide_latent, video_strength, scale_factors, guide_mask=guide_mask, latent_downscale_factor=float(latent_downscale_factor), causal_fix=causal_fix
                    )
                    if is_lora_active:
                        positive = _append_guide_attention_entry(positive, tokens_added, guide_orig_shape, attention_strength=video_attention_strength)
                        negative = _append_guide_attention_entry(negative, tokens_added, guide_orig_shape, attention_strength=video_attention_strength)
                except Exception as e:
                    raise RuntimeError(f"LTX Director Guide motion segment failed for {seg}: {e}") from e

        else:
            print("[LTXDirectorGuide] No timeline guides present. Passing through.")

        exact_crop_frames = max(0, int(latent_image.shape[2]) - initial_latent_length)
        positive = node_helpers.conditioning_set_values(positive, {"nghtdrp_guide_crop_latent_frames": exact_crop_frames})
        negative = node_helpers.conditioning_set_values(negative, {"nghtdrp_guide_crop_latent_frames": exact_crop_frames})

        return (positive, negative, {"samples": latent_image, "noise_mask": noise_mask}, model, float(latent_downscale_factor))

def _conditioning_get_any_value(conditioning, key, default=None):
    for item in conditioning:
        meta = item[1]
        if key in meta and meta.get(key) is not None:
            return meta.get(key)
    return default

def _get_exact_crop_count_from_conditioning(conditioning):
    value = _conditioning_get_any_value(conditioning, "nghtdrp_guide_crop_latent_frames", None)
    if value is not None:
        try:
            return max(0, int(value))
        except Exception:
            return 0
    keyframe_idxs = _conditioning_get_any_value(conditioning, "keyframe_idxs", None)
    if keyframe_idxs is None:
        return 0
    try:
        return int(torch.unique(keyframe_idxs[:, 0, :, 0]).shape[0])
    except Exception:
        return 0

def _get_noise_mask_for_crop(latent):
    latent_image = latent["samples"]
    noise_mask = latent.get("noise_mask", None)
    if noise_mask is None:
        batch, _, frames, _, _ = latent_image.shape
        return torch.ones((batch, 1, frames, 1, 1), dtype=torch.float32, device=latent_image.device)
    return noise_mask.clone()


class LTXDirectorCropGuides:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent": ("LATENT",),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "execute"
    CATEGORY = "WhatDreamsCost"

    def execute(self, positive, negative, latent):
        latent_image = latent["samples"].clone()
        noise_mask = _get_noise_mask_for_crop(latent)

        crop_frames = _get_exact_crop_count_from_conditioning(positive)
        if crop_frames <= 0:
            return (positive, negative, {"samples": latent_image, "noise_mask": noise_mask})

        crop_frames = min(crop_frames, max(0, latent_image.shape[2] - 1))
        if crop_frames > 0:
            latent_image = latent_image[:, :, :-crop_frames]
            noise_mask = noise_mask[:, :, :-crop_frames]

        clear_values = {
            "keyframe_idxs": None,
            "guide_attention_entries": None,
            "nghtdrp_guide_crop_latent_frames": None,
        }
        positive = node_helpers.conditioning_set_values(positive, clear_values)
        negative = node_helpers.conditioning_set_values(negative, clear_values)
        return (positive, negative, {"samples": latent_image, "noise_mask": noise_mask})

NODE_CLASS_MAPPINGS = {
    "LTXDirectorGuide": LTXDirectorGuide,
    "LTXDirectorCropGuides": LTXDirectorCropGuides,
}