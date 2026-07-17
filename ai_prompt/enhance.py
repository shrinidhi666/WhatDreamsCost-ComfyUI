"""
enhance.py -- the AI Prompt core: turn the Director's OWN timeline_data (plus fps/duration
and the panel hint) into a generated GLOBAL prompt + one SEGMENT prompt per timeline beat,
via a local Ollama vision call.

Pure logic, deliberately importable OUTSIDE ComfyUI (no server / comfy / folder_paths
imports here) so it can be tested standalone. The ComfyUI glue -- route registration,
queue guard, VRAM eviction -- lives in routes.py.

The timeline_data string is the node's OWN serialization (the same JSON commitChanges
writes and the Guide's execute parses): segments carry start/length (frames), prompt,
imageFile (input-folder path) and/or imageB64 (browser-drawn frame for videos); the msr
block carries the MSR panel references. No parallel schema exists -- this module reads
what the Director already writes.
"""

import json
import logging
import os

from . import ollama_client
from . import perception
from . import prompt_builder

log = logging.getLogger(__name__)

# Main-track segment types that form story beats. "ghost" segments (visual filler) and
# anything unknown are skipped -- they hold no story content.
_BEAT_TYPES = ("image", "video", "text")


def resolve_input_file(name, input_dir):
    """Resolve a timeline media path against the ComfyUI input folder: input_dir/name
    first, then input_dir/whatdreamscost/basename (the pack's chunk-upload target) -- the
    same convention the Director's own loaders use. Containment-checked (a hostile path in
    a hand-edited timeline JSON must not escape the input folder). Returns an absolute
    path or None when the file does not exist."""
    if not name:
        return None
    for candidate in (os.path.join(input_dir, name),
                      os.path.join(input_dir, "whatdreamscost", os.path.basename(name))):
        real = os.path.realpath(candidate)
        if not real.startswith(os.path.realpath(input_dir)):
            return None
        if os.path.isfile(real):
            return real
    return None


def _story_segments(tdata):
    """The main-track story beats, in time order -- the ONE definition, shared by the
    request builder and the perception pass so their beat lists can never diverge."""
    segs = [s for s in (tdata.get("segments") or [])
            if isinstance(s, dict) and s.get("type") in _BEAT_TYPES]
    segs.sort(key=lambda s: s.get("start", 0))
    return segs


def _beat_image_b64(seg, input_dir):
    """The vision image for one timeline segment: the input-folder file when it exists,
    else the serialized browser frame (imageB64 -- how video segments carry their first
    frame). None when the segment has no visual (e.g. a text segment)."""
    path = resolve_input_file(seg.get("imageFile", ""), input_dir)
    if path:
        return ollama_client.file_to_b64(path)
    b64 = seg.get("imageB64") or ""
    if b64:
        return ollama_client.data_url_to_b64(b64)
    return None


def collect_msr_refs(payload, input_dir):
    """Resolve the MSR panel references (pass-1 inputs): returns (ref_images_b64, count)
    where the list is subjects in panel order followed by the background, or ([], 0) when
    the panel is empty. The BACKGROUND is the one required reference; subjects are OPTIONAL
    (V2 contract: a background-only panel is a valid scene-only run). A background-less
    panel and missing files are HARD errors -- a silently absent identity reference would
    generate a prompt that binds to nothing."""
    try:
        tdata = json.loads(payload.get("timeline_data") or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"timeline_data is not valid JSON: {e}")
    msr = tdata.get("msr") or {}
    subjects = [s for s in (msr.get("subjects") or []) if s][:prompt_builder.MAX_MSR_SUBJECTS]
    background = msr.get("background") or ""
    if not subjects and not background:
        return [], 0
    if not background:
        raise ValueError("MSR needs a background (scene) reference on the panel; "
                         "subjects are optional.")
    images = []
    for j, name in enumerate(subjects, start=1):
        path = resolve_input_file(name, input_dir)
        if not path:
            raise ValueError(f"MSR subject {j} file not found in the input folder: {name}")
        images.append(ollama_client.file_to_b64(path))
    bg_path = resolve_input_file(background, input_dir)
    if not bg_path:
        raise ValueError(f"MSR background file not found in the input folder: {background}")
    images.append(ollama_client.file_to_b64(bg_path))
    return images, len(subjects)


def build_request(payload, input_dir, enumeration="", msr_subjects=0, global_only=False,
                  perception_data=None):
    """Turn the endpoint payload into the PASS-2 pieces:
    (vision_prompt, system, images_b64, segments_out). The images are the BEAT frames
    ONLY -- MSR references never enter this call; they arrive as `enumeration`, the
    finished text composed from pass 1.

    payload keys:
      timeline_data    -- the Director's serialized timeline JSON string (required)
      fps              -- frames per second (the Director's frame_rate widget)
      duration_frames  -- the clip length in frames (used only for invented windows)
      hint             -- the AI Prompt panel's user direction ("" = none)
      segments_wanted  -- desired TOTAL beat count (see the invention block below)

    The user's EXISTING texts ride along as the story's ground truth: each segment's
    prompt (already in the beats) and the node's global prompt (timeline_data's
    global_prompt key -- whitespace-collapsed only, never content-edited). The fidelity
    law lives in prompt_builder.build_vision_prompt.

    perception_data -- output of _perceive_timeline (None = perception off, everything
    identical to before): {"by_id": {segment_id: {kind, desc, seconds, audio_desc}},
    "timeline_audio": [{"label", "desc"}], "audio_notes": [fallback note lines for
    clips the perception pass could not read]}. With it, the writing call carries no
    images; segment ids are remapped here to FINAL beat numbers (invention can insert
    beats, so positions are only known after the invention step).

    segments_out is the response scaffold: one entry per beat, in time order, with the
    timeline segment id (or None for invented beats) and its start/length in frames --
    the prompt field is filled in by the caller after parse_sections.
    """
    try:
        tdata = json.loads(payload.get("timeline_data") or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"timeline_data is not valid JSON: {e}")

    if tdata.get("retakeMode"):
        raise ValueError("AI Prompt works on the normal timeline. Leave Retake Mode first.")

    fps = float(payload.get("fps") or 24)
    if fps <= 0:
        raise ValueError("fps must be > 0.")
    duration_frames = int(payload.get("duration_frames") or 0)

    # --- Story beats from the main track, in time order.
    segs = _story_segments(tdata)

    perception_on = perception_data is not None
    beats, images, segments_out = [], [], []
    for seg in segs:
        # With the perception pass active the writing call carries NO media -- the
        # beats arrive as faithful text descriptions instead of image attachments.
        b64 = None if perception_on else _beat_image_b64(seg, input_dir)
        if b64:
            images.append(b64)
        length = int(seg.get("length", 0)) or 1
        beats.append({
            "seconds": length / fps,
            "has_image": b64 is not None,
            "text": (seg.get("prompt") or "").strip(),
        })
        segments_out.append({
            "id": seg.get("id"),
            "start": int(seg.get("start", 0)),
            "length": length,
        })

    # --- Invent beats up to the requested TOTAL: `segments_wanted` is the desired beat
    # count for the whole clip. Existing segments already count as beats (their rough text
    # is enhanced in place); when more are wanted, the UNCOVERED duration -- the gaps
    # before/between/after the existing segments -- is chopped into the remaining windows,
    # in time order, sized proportionally to each gap. With an empty timeline this is the
    # CLI's image-less mode (all beats invented).
    want = int(payload.get("segments_wanted") or 1)
    if want < 1:
        raise ValueError("segments_wanted must be >= 1.")
    if global_only:
        # Beats are context only in this mode -- a single full-clip window suffices when
        # the timeline is empty; existing segments stay as-is (no invention, no writes).
        want = min(want, max(1, len(beats)) if beats else 1)
    extra = want - len(beats)
    if extra > 0 and duration_frames > 0:
        spans = sorted((e["start"], e["start"] + e["length"]) for e in segments_out)
        gaps, cursor = [], 0
        for a, b in spans:
            if a > cursor:
                gaps.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < duration_frames:
            gaps.append((cursor, duration_frames))
        total_gap = sum(b - a for a, b in gaps)
        if not segments_out and total_gap < extra:
            raise ValueError("The clip duration is shorter than the requested segment count.")
        if total_gap > 0:
            # Largest-remainder proportional allocation of the extra windows over the gaps.
            quotas = [(extra * (b - a)) // total_gap for a, b in gaps]
            remainders = sorted(range(len(gaps)),
                                key=lambda i: (extra * (gaps[i][1] - gaps[i][0])) % total_gap,
                                reverse=True)
            for i in remainders[:extra - sum(quotas)]:
                quotas[i] += 1
            pairs = list(zip(segments_out, beats))
            for (a, b), q in zip(gaps, quotas):
                q = min(q, b - a)   # never mint zero-length windows in a tiny gap
                if q <= 0:
                    continue
                base, rem = divmod(b - a, q)
                start = a
                for i in range(q):
                    length = base + (1 if i < rem else 0)
                    pairs.append((
                        {"id": None, "start": start, "length": length},
                        {"seconds": length / fps, "has_image": False, "text": ""},
                    ))
                    start += length
            pairs.sort(key=lambda p: p[0]["start"])
            segments_out = [p[0] for p in pairs]
            beats = [p[1] for p in pairs]

    has_perceived_media = bool(perception_on and (perception_data.get("by_id")
                                                  or perception_data.get("timeline_audio")))
    if not images and not enumeration and not has_perceived_media:
        raise ValueError("Nothing to look at: add images/videos to the timeline or MSR "
                         "references on the panel (or both) before generating.")

    # --- Imported audio as text context (the model cannot hear; this is metadata only).
    # With perception on, the clips were actually HEARD -- only the unreadable ones keep
    # a bare note line; the heard ones arrive in the MEDIA DESCRIPTIONS block instead.
    if perception_on:
        audio_notes = list(perception_data.get("audio_notes") or [])
    else:
        audio_notes = []
        for a in (tdata.get("audioSegments") or []):
            if not isinstance(a, dict):
                continue
            name = os.path.basename(a.get("audioFile") or a.get("fileName") or "") or "imported audio"
            start_s = int(a.get("start", 0)) / fps
            length_s = (int(a.get("length", 0)) or 0) / fps
            audio_notes.append(f"clip '{name}' plays from {start_s:.1f}s for {length_s:.1f}s")

    # --- Remap perception results from segment ids to FINAL beat numbers.
    perceptions = None
    if perception_on:
        by_id = perception_data.get("by_id") or {}
        p_beats, p_audio = {}, {}
        for idx, entry in enumerate(segments_out, start=1):
            p = by_id.get(entry["id"]) if entry["id"] is not None else None
            if not p:
                continue
            p_beats[idx] = {"kind": p["kind"], "desc": p["desc"],
                            "seconds": p.get("seconds")}
            if p.get("audio_desc"):
                p_audio[idx] = p["audio_desc"]
        timeline_audio = list(perception_data.get("timeline_audio") or [])
        if p_beats or p_audio or timeline_audio:
            perceptions = {"beats": p_beats, "beat_audio": p_audio,
                           "timeline_audio": timeline_audio}

    existing_global = " ".join((tdata.get("global_prompt") or "").split())

    prompt = prompt_builder.build_vision_prompt(
        beats, enumeration=enumeration, msr_subjects=msr_subjects, audio_notes=audio_notes,
        motion=(payload.get("motion") or "free"),
        camera=(payload.get("camera") or "free"),
        audio=(payload.get("audio") or "full"),
        hint=(payload.get("hint") or ""),
        global_only=global_only,
        global_text=existing_global,
        perceptions=perceptions,
    )
    return prompt, prompt_builder.load_system_skill(), images, segments_out


def _perceive_timeline(tdata, input_dir, fps, call_vision):
    """The perception pass: every beat's media watched/heard, one MODALITY per call
    (frames of one video together; audio always alone -- mixing loses the audio, tested).

    Returns ({segment_id: {kind, desc, seconds, audio_desc}},
             [{label, desc}] for timeline audio clips,
             [fallback note lines] for clips that could not be read,
             call_count).
    Missing video files degrade honestly to their browser first-frame (logged); missing
    audio files keep today's bare filename note."""
    by_id, timeline_audio, fallback_notes, n_calls = {}, [], [], 0

    for seg in _story_segments(tdata):
        sid = seg.get("id")
        stype = seg.get("type")
        if stype == "video":
            path = resolve_input_file(seg.get("imageFile", ""), input_dir)
            length = int(seg.get("length", 0)) or 1
            duration = length / fps
            trim = float(seg.get("trimStart", 0) or 0) / fps
            if path:
                frames, used_fps = perception.extract_frames(path, trim, duration)
                desc = call_vision(
                    perception.video_reading_prompt(len(frames), used_fps, duration),
                    frames)
                n_calls += 1
                audio_desc = None
                audio_b64 = perception.extract_audio(path, trim, duration)
                if audio_b64:
                    audio_desc = call_vision(perception.audio_reading_prompt(), [audio_b64])
                    n_calls += 1
                by_id[sid] = {"kind": "video", "desc": desc, "seconds": duration,
                              "audio_desc": audio_desc}
                continue
            log.warning("[AI Prompt] video file for segment %s not found in the input "
                        "folder; perceiving its first frame only.", sid)
            # fall through to the image path below (browser frame)
        b64 = _beat_image_b64(seg, input_dir)
        if b64 is None:
            continue    # text segment / no visual -- nothing to perceive
        desc = call_vision(perception.beat_image_reading_prompt(), [b64])
        n_calls += 1
        by_id[sid] = {"kind": "image", "desc": desc, "seconds": None, "audio_desc": None}

    for a in (tdata.get("audioSegments") or []):
        if not isinstance(a, dict):
            continue
        name = os.path.basename(a.get("audioFile") or a.get("fileName") or "") or "imported audio"
        start_s = int(a.get("start", 0)) / fps
        length_s = (int(a.get("length", 0)) or 0) / fps
        label = f"clip '{name}' plays from {start_s:.1f}s for {length_s:.1f}s"
        path = resolve_input_file(a.get("audioFile") or a.get("fileName") or "", input_dir)
        if not path or length_s <= 0:
            fallback_notes.append(label)
            continue
        offset = float(a.get("trimStart", 0) or 0) / fps
        for w_start, w_len in perception.audio_windows(length_s):
            desc = call_vision(perception.audio_reading_prompt(),
                               [perception.file_audio_b64(path, offset + w_start, w_len)])
            n_calls += 1
            w_label = label if length_s <= perception.AUDIO_WINDOW_SECS else (
                f"{label} (heard {w_start:.0f}s to {w_start + w_len:.0f}s of the clip)")
            timeline_audio.append({"label": w_label, "desc": desc})

    return by_id, timeline_audio, fallback_notes, n_calls


def run(payload, input_dir):
    """The full core, TWO passes when MSR references are on the panel:

    PASS 1 (perception): the reference images ALONE -> one clause per reference
    (SUBJECT j: / SCENE: labels, hard-parsed) -> format_enumeration() composes the
    official V2 "Image N:" global. Low temperature, no thinking -- a faithful
    description task, mirroring vector-lab's see().

    PASS 2 (writing): the beat frames ALONE + the enumeration as fixed text -> GLOBAL
    narration + per-beat SEGMENT prompts. The final global is COMPOSED here:
    enumeration + narration -- so the enumeration can never be dropped, reordered, or
    filled from the wrong image by the writing pass.

    Raises ValueError (bad input / broken output contract) or ollama_client.OllamaError
    (call failure) with user-displayable messages."""
    settings = payload.get("settings") or {}
    model = (settings.get("model") or "").strip()
    if not model:
        raise ValueError("No Ollama model set. Enter a model name in the AI Prompt settings.")
    base_url = (settings.get("url") or "").strip() or ollama_client.DEFAULT_URL
    num_ctx = int(settings.get("num_ctx") or ollama_client.DEFAULT_NUM_CTX)
    keep_alive = settings.get("keep_alive", ollama_client.DEFAULT_KEEP_ALIVE)

    # The optional PERCEPTION model (audio/video capable, e.g. gemma4 12B): when set it
    # reads ALL media -- MSR references, beat images, video frames, audio -- and the
    # writing model gets faithful text only. Empty = feature off, behavior identical to
    # before. vision_think defaults False: tested 10-90x faster with quality intact.
    vision_model = (settings.get("vision_model") or "").strip()
    vision_think = bool(settings.get("vision_think"))

    def call_vision(prompt_text, media_b64):
        return ollama_client.generate_vision(
            prompt_text, media_b64, vision_model, system=None, base_url=base_url,
            temperature=1.0, num_ctx=num_ctx, think=vision_think, keep_alive=keep_alive,
        ).strip()

    # Perception (reference reading + timeline media) runs on the vision model when set,
    # else on the writing model exactly as before.
    ref_model = vision_model or model
    ref_think = vision_think if vision_model else True

    ref_images, msr_count = collect_msr_refs(payload, input_dir)
    enumeration = ""
    if ref_images:
        # ONE image per call: role-specific instruction, nothing else in the call to
        # confuse it with. Subjects in panel order, then the scene.
        def read_ref(image_b64, prompt, what):
            raw = ollama_client.generate_vision(
                prompt, [image_b64], ref_model,
                system=None, base_url=base_url,
                temperature=1.0, num_ctx=num_ctx, think=ref_think, keep_alive=keep_alive,
            )
            return prompt_builder.clean_ref_clause(raw, what)

        subject_clauses = [
            read_ref(img, prompt_builder.build_subject_reading_prompt(), f"subject {j}")
            for j, img in enumerate(ref_images[:msr_count], start=1)]
        scene_clause = read_ref(ref_images[msr_count],
                                prompt_builder.build_scene_reading_prompt(), "the scene")
        enumeration = prompt_builder.format_enumeration(subject_clauses, scene_clause)

    # The perception pass proper: timeline media -> faithful text. Runs after the MSR
    # reads so the vision model stays warm across ALL perception calls, and before the
    # writing call so keep_alive lets Ollama hand the GPU to the writing model.
    perception_data = None
    n_perception_calls = 0
    if vision_model:
        try:
            tdata = json.loads(payload.get("timeline_data") or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"timeline_data is not valid JSON: {e}")
        if not tdata.get("retakeMode"):
            fps = float(payload.get("fps") or 24)
            if fps <= 0:
                raise ValueError("fps must be > 0.")
            by_id, timeline_audio, fallback_notes, n_perception_calls = \
                _perceive_timeline(tdata, input_dir, fps, call_vision)
            perception_data = {"by_id": by_id, "timeline_audio": timeline_audio,
                               "audio_notes": fallback_notes}

    global_only = bool(payload.get("global_only"))
    prompt, system, images, segments_out = build_request(payload, input_dir,
                                                         enumeration=enumeration,
                                                         msr_subjects=msr_count,
                                                         global_only=global_only,
                                                         perception_data=perception_data)

    # The MSR enumeration-only shape (official V2 pattern): references present, real
    # segments to carry the story, and NOT global-only. There the GLOBAL is the fixed
    # enumeration alone and every beat carries the narration. When MSR references are
    # present but global-only is on, the whole story is forced into the global instead
    # (nowhere else to put it) -- functional, but NOT the trained pattern; flag it.
    msr_enum_shape = bool(enumeration) and not global_only
    if enumeration and global_only:
        log.warning("[AI Prompt] MSR references with 'global only' writes the whole story into "
                    "the global prompt. The official MSR pattern keeps the global to the "
                    "enumeration and puts the story in timeline segments -- uncheck 'global only' "
                    "and add text segments for the trained behavior.")

    raw = ollama_client.generate_vision(
        prompt, images, model,
        system=system or None,
        base_url=base_url,
        temperature=1.0,
        num_ctx=num_ctx,
        think=True,
        keep_alive=keep_alive,
    )
    n_expected = 0 if global_only else len(segments_out)
    global_prompt, seg_prompts = prompt_builder.parse_sections(
        raw, n_expected, allow_empty_global=msr_enum_shape)
    if enumeration:
        global_prompt = f"{enumeration}\n{global_prompt}".strip()
    if global_only:
        segments_out = []
    for entry, text in zip(segments_out, seg_prompts):
        entry["prompt"] = text
    meta = {"model": model, "images": len(images) + len(ref_images),
            "enumerated": bool(enumeration), "global_only": global_only}
    if vision_model:
        meta["vision_model"] = vision_model
        meta["perception_calls"] = n_perception_calls
    return {
        "global": global_prompt,
        "segments": segments_out,
        "meta": meta,
    }
