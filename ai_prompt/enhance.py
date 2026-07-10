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
import os

from . import ollama_client
from . import prompt_builder

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


def build_request(payload, input_dir):
    """Turn the endpoint payload into (vision_prompt, system, images_b64, segments_out).

    payload keys:
      timeline_data    -- the Director's serialized timeline JSON string (required)
      fps              -- frames per second (the Director's frame_rate widget)
      duration_frames  -- the clip length in frames (used only for invented windows)
      hint             -- the AI Prompt panel's user direction ("" = none)
      segments_wanted  -- how many beats to invent when the timeline has none (>=1)

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
    segs = [s for s in (tdata.get("segments") or [])
            if isinstance(s, dict) and s.get("type") in _BEAT_TYPES]
    segs.sort(key=lambda s: s.get("start", 0))

    beats, images, segments_out = [], [], []
    for seg in segs:
        b64 = _beat_image_b64(seg, input_dir)
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

    # --- MSR references from the Director's MSR panel (subjects first, background last --
    # the panel order IS the enumeration order). A missing reference file is a HARD error:
    # a silently absent identity reference would generate a prompt that binds to nothing.
    msr = tdata.get("msr") or {}
    subjects = [s for s in (msr.get("subjects") or []) if s][:prompt_builder.MAX_MSR_SUBJECTS]
    background = msr.get("background") or ""
    msr_count = 0
    msr_bg = False
    if subjects or background:
        if not subjects or not background:
            raise ValueError("MSR needs at least one subject AND a background on the panel.")
        for j, name in enumerate(subjects, start=1):
            path = resolve_input_file(name, input_dir)
            if not path:
                raise ValueError(f"MSR subject {j} file not found in the input folder: {name}")
            images.append(ollama_client.file_to_b64(path))
            msr_count += 1
        bg_path = resolve_input_file(background, input_dir)
        if not bg_path:
            raise ValueError(f"MSR background file not found in the input folder: {background}")
        images.append(ollama_client.file_to_b64(bg_path))
        msr_bg = True

    if not images:
        raise ValueError("Nothing to look at: add images/videos to the timeline or MSR "
                         "references on the panel (or both) before generating.")

    # --- Imported audio as text context (the model cannot hear; this is metadata only).
    audio_notes = []
    for a in (tdata.get("audioSegments") or []):
        if not isinstance(a, dict):
            continue
        name = os.path.basename(a.get("audioFile") or a.get("fileName") or "") or "imported audio"
        start_s = int(a.get("start", 0)) / fps
        length_s = (int(a.get("length", 0)) or 0) / fps
        audio_notes.append(f"clip '{name}' plays from {start_s:.1f}s for {length_s:.1f}s")

    prompt = prompt_builder.build_vision_prompt(
        beats, msr_count=msr_count, msr_bg=msr_bg, audio_notes=audio_notes,
        motion=(payload.get("motion") or "free"),
        camera=(payload.get("camera") or "free"),
        audio=(payload.get("audio") or "full"),
        hint=(payload.get("hint") or ""),
    )
    return prompt, prompt_builder.load_system_skill(), images, segments_out


def run(payload, input_dir):
    """The full core: build the request, call Ollama, parse the labeled sections, and
    return the response dict for the browser. Raises ValueError (bad input) or
    ollama_client.OllamaError (call failure) with user-displayable messages."""
    settings = payload.get("settings") or {}
    model = (settings.get("model") or "").strip()
    if not model:
        raise ValueError("No Ollama model set. Enter a model name in the AI Prompt panel.")
    base_url = (settings.get("url") or "").strip() or ollama_client.DEFAULT_URL

    prompt, system, images, segments_out = build_request(payload, input_dir)

    raw = ollama_client.generate_vision(
        prompt, images, model,
        system=system or None,
        base_url=base_url,
        temperature=1.0,
        num_ctx=int(settings.get("num_ctx") or ollama_client.DEFAULT_NUM_CTX),
        think=True,
        keep_alive=settings.get("keep_alive", ollama_client.DEFAULT_KEEP_ALIVE),
    )
    global_prompt, seg_prompts = prompt_builder.parse_sections(raw, len(segments_out))
    for entry, text in zip(segments_out, seg_prompts):
        entry["prompt"] = text
    return {
        "global": global_prompt,
        "segments": segments_out,
        "meta": {"model": model, "images": len(images)},
    }
