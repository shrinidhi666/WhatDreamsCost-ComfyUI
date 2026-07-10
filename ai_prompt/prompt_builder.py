"""
prompt_builder.py -- builds the vision prompt for the AI Prompt feature and parses the
model's labeled output back into (global_prompt, [segment prompts]).

Vendored from vector-lab (insta_ltx.py / director_ltx.py) on 2026-07-10. This copy is
authoritative for the node; the vector-lab CLI evolves independently. No imports outside
the stdlib -- the node pack stays whole without any outside project.

The contract (unchanged from the CLI):
  - the model receives beat images (timeline keyframes / video first-frames) in time order,
    then MSR subject references, then the MSR background reference, plus a text description
    of every beat window;
  - it outputs LABELED SECTIONS -- "GLOBAL:" then "SEGMENT 1:".."SEGMENT N:" -- one flowing
    present-tense paragraph each. A missing label is a HARD error (fix the prompt, never
    scrub the output).
  - timing flows IN as pacing guidance only; the output prompts must never contain seconds,
    frame numbers, or duration words (node-etched rule -- the Director's frame windows set
    the timing, prompt words must not fight them).
"""

import re
from pathlib import Path

from .axes import AUDIO_DIRECTIVES, CAMERA_CORES, MOTION_CORES

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

# The maximum MSR subject references -- 1-4 subjects + 1 scene is the Licon-MSR LoRA's
# trained contract (see the MSR rules below), not a taste choice.
MAX_MSR_SUBJECTS = 4

_system_skill_cache = None


def load_system_skill():
    """The merged system skill: the LTX prompt-specialist persona + the cinematographer
    persona + the FULL ltx-guide.md (whole, never summarised -- the guide IS the model-
    specific knowledge the personas merely claim). Cached after the first read."""
    global _system_skill_cache
    if _system_skill_cache is None:
        parts = []
        for name in ("ltx_prompt_specialist.md", "ltx_cinematographer.md", "ltx-guide.md"):
            p = _SKILLS_DIR / name
            if p.is_file():
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(text)
        _system_skill_cache = "\n\n".join(parts)
    return _system_skill_cache


# ---- THE MSR RULEBOOK (vendored verbatim from vector-lab director_ltx.py) -------------
# Verified against primary sources there: the official model card
# (huggingface.co/LiconStudio/LTX-2.3-Multiple-Subject-Reference), the official sample
# workflow (ComfyUI-Licon-MSR), the LiconMSR node source, and the LoRA metadata.

MSR_RULES = """THE MSR RULES (etched -- follow ALL, no exceptions):
1. REFERENCE COUNT: 2 to 5 reference images total -- 1 to 4 SUBJECTS plus exactly ONE scene
   reference. Never more, never fewer.
2. ONE SCENE ONLY: a video happens in ONE place, so exactly one reference is the scene, and the
   scene reference is always the LAST one.
3. NUMBERING: references are numbered by their PANEL ORDER -- subjects first (1..k), the scene
   last (k+1, labeled "(scene)"). That numbering is the composed reference clip's own frame
   order; it never changes.
4. ENUMERATION FIRST: the GLOBAL prompt OPENS with the enumeration -- one clause per reference
   ("Reference image 1: ...", "Reference image 2: ...", and so on) -- BEFORE any narration.
5. CONCISE BUT ACCURATE: over-description and under-description BOTH degrade consistency. One
   tight clause per reference, only the distinguishing features -- hair, attire, build, colours
   for a figure; form, material, colours for an object; architecture, palette, light for the
   scene. Nothing more.
6. A SUBJECT IS NOT ONLY A PERSON: a reference may carry a figure's identity, an object/prop,
   a local texture, or a viewpoint. Describe what it plainly IS.
6b. A SUBJECT REFERENCE MAY ITSELF BE A MULTI-VIEW SHEET: the official examples use one
   multi-angle sheet per subject (a character shown from several angles in ONE image; a car as
   a three-angle product sheet) -- the strongest identity signal. Enumerate the SUBJECT the
   sheet depicts (one entity, one clause), never the sheet's individual panels.
7. BIND BY LOOK: after the enumeration, the narration points at every referenced element by the
   EXACT look enumerated for it (never a name), so the reference tokens bind to the prompt
   entities."""


# ---- Locked output rules (vendored from insta_ltx.py, + the node's no-timing rule) ----

LOCKED_RULES = """CRITICAL OUTPUT RULES (follow ALL):
- ASCII ONLY. Straight double quotes, -- for dashes, ... for pauses. No curly quotes,
  no accents, no Unicode.
- PRESENT TENSE throughout. Describe what IS happening, like a cinematographer.
- POSITIVE ONLY. Never write "no", "not", "without", "motionless", "silent". To say
  a figure does not move, write that the figure "holds its posture locked in place".
- NO PROPER NAMES, no place names, no compass directions. Point to each figure by
  what it LOOKS LIKE + its FRAME-POSITION ONLY, e.g. "the figure in the red scarf in
  frame-centre", "the bare-chested archer in frame-left foreground".
- PLAIN-ENGLISH DESCRIPTORS. Describe any creature or being by its plain visual form
  (e.g. "a colossal grey-skinned heavy-jawed creature", "a giant serpent", "a radiant
  being") -- never a culture-specific or mythological label.
- ACTION-LED. ONE main motion idea per segment. Do not invent new props, characters, or
  architecture that are not visible in the image(s).
- NO TIMING WORDS. Never write seconds, frame numbers, durations, counts of time, or
  playback-speed references into any prompt. The segment windows below size HOW MUCH
  happens; the words describe only WHAT happens."""


# ---- The vision prompt ---------------------------------------------------------------

def build_vision_prompt(beats, msr_count=0, msr_bg=False, audio_notes=None,
                        motion="free", camera="free", audio="full"):
    """The Director vision prompt, built from the ACTUAL timeline.

    `beats` -- list of dicts, one per timeline segment IN TIME ORDER:
        {"seconds": float,          # the segment's real window length
         "has_image": bool,         # True when a frame image is supplied for this beat
         "text": str}               # the user's existing rough prompt text ("" if none)
    Beats WITH an image consume vision-call IMAGE slots 1..n in order; the intro states
    the beat -> IMAGE mapping explicitly. MSR subject references follow (msr_count of
    them), then the MSR background reference when msr_bg is True.
    `audio_notes` -- optional list of plain-text lines describing imported audio clips
    (context only; the model cannot hear them).
    `motion` / `camera` / `audio` -- the three orthogonal axes (see axes.py). The inert
    defaults ("free"/"free"/"full") inject nothing; other choices inject their directive
    block in the CLI's exact order: motion core, MSR block, camera, audio, locked rules.
    """
    if motion not in MOTION_CORES:
        raise ValueError(f"Unknown motion '{motion}'. Choices: {list(MOTION_CORES)}")
    if camera not in CAMERA_CORES:
        raise ValueError(f"Unknown camera '{camera}'. Choices: {list(CAMERA_CORES)}")
    if audio not in AUDIO_DIRECTIVES:
        raise ValueError(f"Unknown audio '{audio}'. Choices: {list(AUDIO_DIRECTIVES)}")
    n_segments = len(beats)
    if n_segments < 1:
        raise ValueError("build_vision_prompt needs at least one beat.")

    lines = [
        "You are an LTX 2.3 DIRECTOR prompt writer for one continuous cinematic clip built from",
        f"{n_segments} story beat(s). You are given, in order:",
    ]
    img_idx = 0
    any_image = False
    for i, b in enumerate(beats, start=1):
        if b.get("has_image"):
            img_idx += 1
            any_image = True
            lines.append(f"  IMAGE {img_idx} = story BEAT {i} -- the frame the clip passes through"
                         f" at beat {i} (beats run in time order; each beat is one timeline"
                         " segment).")
        else:
            lines.append(f"  (story BEAT {i} has NO frame image -- invent what happens in it from"
                         " the surrounding beats, the references, and the beat notes below.)")
    if msr_count:
        for j in range(1, msr_count + 1):
            img_idx += 1
            lines.append(f"  IMAGE {img_idx} = MSR SUBJECT reference {j} -- an IDENTITY reference"
                         " for one recurring figure (what they look like; NOT a frame of the"
                         " video).")
        if msr_bg:
            img_idx += 1
            lines.append(f"  IMAGE {img_idx} = MSR BACKGROUND reference -- the scene/location"
                         " identity reference (NOT a frame of the video).")
    if not any_image and msr_count:
        lines += [
            "",
            "There are NO beat frames for this clip -- ONLY the identity references above exist.",
            f"INVENT the {n_segments} story beat(s) yourself: what these referenced subjects do in",
            "the referenced scene, one beat per timeline segment, following the user direction if",
            "one is given.",
        ]

    # Beat windows: pacing guidance ONLY (the no-timing locked rule keeps numbers out of
    # the written prompts). Existing segment text is the user's rough intent -- honor it.
    lines += ["", "BEAT WINDOWS AND NOTES (pacing guidance ONLY -- per the timing rule, these"
                  " numbers NEVER appear in your written prompts):"]
    for i, b in enumerate(beats, start=1):
        window = f"  BEAT {i}: about {b['seconds']:.1f}s of screen time"
        secs = b["seconds"]
        if secs <= 2.5:
            window += " -- brief; ONE clean action, nothing more."
        elif secs <= 5.0:
            window += " -- room for one developed action with a clear arc."
        else:
            window += " -- long; the action can build, land, and settle."
        lines.append(window)
        if b.get("text"):
            lines.append(f"    The user's rough intent for this beat (honor it, write it properly):"
                         f" {b['text']}")

    if audio_notes:
        lines += ["", "TIMELINE AUDIO (context only -- you cannot hear these; acknowledge sound"
                      " that overlaps a beat where it plainly fits):"]
        for note in audio_notes:
            lines.append(f"  {note}")

    lines += [
        "",
        "Your job: write the Director prompt set for this clip -- ONE GLOBAL prompt that anchors",
        "the whole clip (subjects, setting, light, overall arc), and ONE SEGMENT prompt per beat",
        "that narrates ONLY what happens inside that beat's window, in present tense, flowing",
        "naturally out of the previous beat and into the next (one continuous shot, never a",
        "scene cut).",
    ]
    intro = "\n".join(lines)

    msr_block = ""
    if msr_count:
        # The enumeration numbers references by their MSR PANEL order (subjects first,
        # background last) -- NOT the vision-call IMAGE numbers above, so each line states
        # the mapping explicitly to kill the ambiguity.
        n_beat_images = sum(1 for b in beats if b.get("has_image"))
        ref_lines = []
        for j in range(1, msr_count + 1):
            ref_lines.append(
                f"  Reference image {j}: <the look of MSR SUBJECT reference {j} -- that is"
                f" IMAGE {n_beat_images + j} above -- hair, attire, build, colours>."
            )
        if msr_bg:
            scene_no = msr_count + 1
            ref_lines.append(
                f"  Reference image {scene_no} (scene): <the look of the MSR BACKGROUND reference"
                f" -- that is IMAGE {n_beat_images + scene_no} above>."
            )
        msr_block = (
            MSR_RULES + "\n\n"
            "For THIS run the enumeration is EXACTLY these lines, in this order (the numbering is\n"
            "the MSR panel order per rule 3 -- NOT the IMAGE numbers of this vision call):\n"
            + "\n".join(ref_lines) + "\n"
            "Fill each from its actual reference image, then narrate the clip under rule 7.\n\n"
        )

    # Axis blocks, in the CLI's exact order: motion core first, then MSR, then camera and
    # audio (placed after the core so they override any camera/audio the core implies).
    # The inert defaults are all empty strings -- a free/free/full run injects nothing.
    core = MOTION_CORES[motion]
    core_block = f"{core}\n\n" if core else ""
    camera_block = CAMERA_CORES[camera]
    audio_block = AUDIO_DIRECTIVES[audio]

    seg_labels = "\n".join(f"SEGMENT {i}: <present-tense paragraph for beat {i}'s window ONLY>"
                           for i in range(1, n_segments + 1))
    task = (
        "\n\nNOW WRITE THE DIRECTOR PROMPTS. Output ONLY these labeled sections, each label at the"
        " start of its own line, exactly:\n"
        "GLOBAL: <one flowing paragraph anchoring the whole clip"
        + (" -- opening with the MSR reference enumeration" if msr_count else "")
        + ">\n"
        + seg_labels + "\n"
        "No preamble, no JSON, no headings beyond those labels, no bullets. Strictly ASCII."
    )
    return f"{intro}\n\n{core_block}{msr_block}{camera_block}{audio_block}{LOCKED_RULES}{task}"


def with_hint(prompt, hint):
    """Append an explicit user-direction block to the vision prompt. Empty hint returns the
    prompt unchanged. (Vendored verbatim from insta_ltx._with_hint.)"""
    if not hint or not hint.strip():
        return prompt
    return (prompt
            + "\n\nUSER DIRECTION (steer the motion toward this -- but keep ALL the "
            + "locked output rules above):\n  "
            + hint.strip())


# ---- The labeled-sections parser (the output contract) --------------------------------

_LABEL_RE = re.compile(r"^\s*(GLOBAL|SEGMENT\s+(\d+))\s*:\s*", re.IGNORECASE | re.MULTILINE)


def parse_sections(text, n_segments):
    """Parse the model's labeled sections into (global_prompt, [segment_1..segment_n]).
    HARD error on any missing label -- the contract is the prompt's job to enforce, never a
    downstream scrub. Extra text before the first label (e.g. thinking remnants) is ignored.
    (Vendored verbatim from director_ltx.parse_sections.)"""
    matches = list(_LABEL_RE.finditer(text or ""))
    if not matches:
        raise ValueError("Model output has no GLOBAL:/SEGMENT N: labels. Full output:\n" + str(text))
    found = {}
    for k, m in enumerate(matches):
        body_end = matches[k + 1].start() if k + 1 < len(matches) else len(text)
        body = text[m.end():body_end].strip()
        key = "GLOBAL" if m.group(1).upper().startswith("GLOBAL") else int(m.group(2))
        if key in found:
            raise ValueError(f"Model output repeats the {key} label.")
        found[key] = " ".join(body.split())
    if "GLOBAL" not in found or not found["GLOBAL"]:
        raise ValueError("Model output is missing a non-empty GLOBAL section.")
    segments = []
    for i in range(1, n_segments + 1):
        if i not in found or not found[i]:
            raise ValueError(f"Model output is missing a non-empty SEGMENT {i} section "
                             f"(expected {n_segments} segments).")
        segments.append(found[i])
    return found["GLOBAL"], segments
