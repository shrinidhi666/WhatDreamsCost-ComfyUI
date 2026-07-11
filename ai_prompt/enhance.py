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


def collect_msr_refs(payload, input_dir):
    """Resolve the MSR panel references (pass-1 inputs): returns (ref_images_b64, count)
    where the list is subjects in panel order followed by the background, or ([], 0) when
    the panel is empty. Half-filled panels and missing files are HARD errors -- a silently
    absent identity reference would generate a prompt that binds to nothing."""
    try:
        tdata = json.loads(payload.get("timeline_data") or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"timeline_data is not valid JSON: {e}")
    msr = tdata.get("msr") or {}
    subjects = [s for s in (msr.get("subjects") or []) if s][:prompt_builder.MAX_MSR_SUBJECTS]
    background = msr.get("background") or ""
    if not subjects and not background:
        return [], 0
    if not subjects or not background:
        raise ValueError("MSR needs at least one subject AND a background on the panel.")
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


def build_request(payload, input_dir, enumeration="", global_only=False):
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

    if not images and not enumeration:
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
        beats, enumeration=enumeration, audio_notes=audio_notes,
        motion=(payload.get("motion") or "free"),
        camera=(payload.get("camera") or "free"),
        audio=(payload.get("audio") or "full"),
        hint=(payload.get("hint") or ""),
        global_only=global_only,
    )
    return prompt, prompt_builder.load_system_skill(), images, segments_out


def run(payload, input_dir):
    """The full core, TWO passes when MSR references are on the panel:

    PASS 1 (perception): the reference images ALONE -> one clause per reference
    (SUBJECT j: / SCENE: labels, hard-parsed) -> format_enumeration() composes the
    official "Reference image N:" opening. Low temperature, no thinking -- a faithful
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
        raise ValueError("No Ollama model set. Enter a model name in the AI Prompt panel.")
    base_url = (settings.get("url") or "").strip() or ollama_client.DEFAULT_URL
    num_ctx = int(settings.get("num_ctx") or ollama_client.DEFAULT_NUM_CTX)
    keep_alive = settings.get("keep_alive", ollama_client.DEFAULT_KEEP_ALIVE)

    ref_images, msr_count = collect_msr_refs(payload, input_dir)
    enumeration = ""
    if msr_count:
        # ONE image per call: role-specific instruction, nothing else in the call to
        # confuse it with. Subjects in panel order, then the scene.
        def read_ref(image_b64, prompt, what):
            raw = ollama_client.generate_vision(
                prompt, [image_b64], model,
                system=None, base_url=base_url,
                temperature=0.4, num_ctx=num_ctx, think=False, keep_alive=keep_alive,
            )
            return prompt_builder.clean_ref_clause(raw, what)

        subject_clauses = [
            read_ref(img, prompt_builder.build_subject_reading_prompt(), f"subject {j}")
            for j, img in enumerate(ref_images[:msr_count], start=1)]
        scene_clause = read_ref(ref_images[msr_count],
                                prompt_builder.build_scene_reading_prompt(), "the scene")
        enumeration = prompt_builder.format_enumeration(subject_clauses, scene_clause)

    global_only = bool(payload.get("global_only"))
    prompt, system, images, segments_out = build_request(payload, input_dir,
                                                         enumeration=enumeration,
                                                         global_only=global_only)
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
    global_prompt, seg_prompts = prompt_builder.parse_sections(raw, n_expected)
    if enumeration:
        global_prompt = f"{enumeration} {global_prompt}"
    if global_only:
        segments_out = []
    for entry, text in zip(segments_out, seg_prompts):
        entry["prompt"] = text
    return {
        "global": global_prompt,
        "segments": segments_out,
        "meta": {"model": model, "images": len(images) + len(ref_images),
                 "enumerated": bool(enumeration), "global_only": global_only},
    }
