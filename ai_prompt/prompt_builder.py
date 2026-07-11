"""
prompt_builder.py -- builds the vision prompt for the AI Prompt feature and parses the
model's labeled output back into (global_prompt, [segment prompts]).

Vendored from vector-lab (insta_ltx.py / director_ltx.py) on 2026-07-10. This copy is
authoritative for the node; the vector-lab CLI evolves independently. No imports outside
the stdlib -- the node pack stays whole without any outside project.

The contract (TWO-PASS, a departure from the CLI's single call -- a subject reference was
once described from the keyframe next to it, because a flat image list forces the model to
COUNT images):
  - PASS 1 (references only, when MSR refs exist): the model sees ONLY the subject
    reference(s) + the scene reference and returns one clause per image (SUBJECT j: /
    SCENE: labels, hard-parsed). format_enumeration() composes the official
    "Reference image N:" enumeration from those clauses.
  - PASS 2 (the writing pass): the model sees ONLY the beat images, receives the
    enumeration as FIXED TEXT, and writes LABELED SECTIONS -- "GLOBAL:" (narration only;
    the caller prepends the enumeration) then "SEGMENT 1:".."SEGMENT N:" -- one flowing
    present-tense paragraph each. A missing label is a HARD error (fix the prompt, never
    scrub the output).
  - timing flows IN as pacing guidance only; the output prompts must never contain seconds,
    frame numbers, or duration words. Node-etched punctuation law: no hyphens or dashes of
    any kind in generated prompts -- only letters, digits, spaces, . , ! " and apostrophes.
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
- LIMITED PUNCTUATION, ASCII ONLY. Your writing uses ONLY letters, digits, spaces and
  these marks: period, comma, exclamation mark, straight double quotes, apostrophe.
  NEVER write a hyphen or dash of ANY kind, even inside words: write "close up",
  "mid shot", "warm toned", "frame left" (never "close-up", "frame-left", never "--").
  No colons, no semicolons, no parentheses, no question marks, no curly quotes, no
  accents, no Unicode. Use ... for pauses. (Sole exception: when a fixed reference
  enumeration is given to you, its "Reference image N:" labels keep their colon.)
- PRESENT TENSE throughout. Describe what IS happening, like a cinematographer.
- POSITIVE ONLY. Never write "no", "not", "without", "motionless", "silent". To say
  a figure does not move, write that the figure "holds its posture locked in place".
- NO PROPER NAMES, no place names, no compass directions. Point to each figure by
  what it LOOKS LIKE and its FRAME POSITION ONLY, e.g. "the figure in the red scarf in
  frame centre", "the bare chested archer in frame left foreground".
- PLAIN ENGLISH DESCRIPTORS. Describe any creature or being by its plain visual form
  (e.g. "a colossal grey skinned heavy jawed creature", "a giant serpent", "a radiant
  being"), never a culture specific or mythological label.
- ACTION LED. ONE main motion idea per segment. Do not invent new props, characters, or
  architecture that are not visible in the image(s), with ONE exception: elements THE
  USER'S BRIEF explicitly asks for ARE allowed; introduce them in plain visual terms
  (look and frame position), exactly like everything else.
- NO TIMING WORDS. Never write seconds, frame numbers, durations, counts of time, or
  playback speed references into any prompt. The segment windows below size HOW MUCH
  happens; the words describe only WHAT happens."""


# ---- Pass 1: reference reading (perception only) ---------------------------------------
#
# WHY TWO PASSES: a vision call receives a FLAT, unlabeled image list, and a text-only
# mapping ("IMAGE 2 = MSR SUBJECT reference 1") requires the model to COUNT images --
# multi-image ordinal binding is unreliable, and a subject reference was once described
# from the keyframe sitting next to it. So the references are read ALONE in their own
# call (nothing else to confuse them with), and the main pass receives the finished
# enumeration as FIXED TEXT -- attribution never depends on counting again.

def build_ref_reading_prompt(msr_count):
    """The pass-1 prompt: msr_count SUBJECT references followed by ONE SCENE reference,
    each to be described in one tight clause. Labeled output, hard-parsed."""
    if msr_count < 1:
        raise ValueError("build_ref_reading_prompt needs at least one subject.")
    lines = [
        "You are reading IDENTITY REFERENCE images for a video's identity lock.",
        f"You are shown {msr_count + 1} images, in this exact order:",
    ]
    for j in range(1, msr_count + 1):
        lines.append(f"  IMAGE {j} = SUBJECT reference {j} -- one recurring figure, object or"
                     " prop. It may itself be a MULTI-VIEW SHEET (the same entity from several"
                     " angles in one image): describe the ONE entity it depicts, never the"
                     " sheet's individual panels.")
    lines.append(f"  IMAGE {msr_count + 1} = the SCENE reference -- the location the video"
                 " happens in.")
    lines += [
        "",
        "For EACH image write ONE tight clause with only the distinguishing features:",
        "hair, attire, build, colours for a figure; form, material, colours for an object;",
        "architecture, palette, light for the scene. Over description and under description",
        "BOTH degrade consistency. Plain visual English, no proper names, no mythological",
        "labels. PUNCTUATION: only letters, digits, spaces, periods, commas and apostrophes",
        "inside the clauses. NEVER a hyphen or dash, even inside words (write \"gold trimmed\",",
        "never \"gold-trimmed\"). Strictly ASCII.",
        "",
        "Output ONLY these labeled lines, each label at the start of its own line, exactly:",
    ]
    for j in range(1, msr_count + 1):
        lines.append(f"SUBJECT {j}: <one clause for IMAGE {j}>")
    lines.append(f"SCENE: <one clause for IMAGE {msr_count + 1}>")
    lines.append("No preamble, no extra lines.")
    return "\n".join(lines)


_REF_LABEL_RE = re.compile(r"^\s*(SUBJECT\s+(\d+)|SCENE)\s*:\s*", re.IGNORECASE | re.MULTILINE)


def parse_ref_readings(text, msr_count):
    """Parse pass-1 output into (subject_clauses, scene_clause). HARD error on any missing
    or empty label -- contract style, never scrubbed."""
    matches = list(_REF_LABEL_RE.finditer(text or ""))
    if not matches:
        raise ValueError("Reference-reading output has no SUBJECT/SCENE labels. Full output:\n"
                         + str(text))
    found = {}
    for k, m in enumerate(matches):
        body_end = matches[k + 1].start() if k + 1 < len(matches) else len(text)
        body = " ".join(text[m.end():body_end].split())
        key = "SCENE" if m.group(1).upper().startswith("SCENE") else int(m.group(2))
        if key in found:
            raise ValueError(f"Reference-reading output repeats the {key} label.")
        found[key] = body
    subjects = []
    for j in range(1, msr_count + 1):
        if not found.get(j):
            raise ValueError(f"Reference-reading output is missing a non-empty SUBJECT {j}.")
        subjects.append(found[j])
    if not found.get("SCENE"):
        raise ValueError("Reference-reading output is missing a non-empty SCENE.")
    return subjects, found["SCENE"]


def format_enumeration(subject_clauses, scene_clause):
    """The exact enumeration text that OPENS the global prompt (MSR rule 4), numbered by
    panel order (rule 3): subjects first, scene last. Composed by US from pass-1 clauses --
    the writing pass can no longer mis-attribute or drop it."""
    def clause(c):
        c = c.strip().rstrip(".")
        return c + "."
    parts = [f"Reference image {j}: {clause(c)}"
             for j, c in enumerate(subject_clauses, start=1)]
    parts.append(f"Reference image {len(subject_clauses) + 1} (scene): {clause(scene_clause)}")
    return " ".join(parts)


# ---- The vision prompt ---------------------------------------------------------------

def build_vision_prompt(beats, enumeration="", audio_notes=None,
                        motion="free", camera="free", audio="full", hint="",
                        global_only=False):
    """The Director vision prompt (pass 2 of the two-pass flow), built from the ACTUAL
    timeline. The ONLY images this pass receives are the beat frames -- the MSR references
    were already read by pass 1 and arrive here as `enumeration`, finished text.

    `beats` -- list of dicts, one per timeline segment IN TIME ORDER:
        {"seconds": float,          # the segment's real window length
         "has_image": bool,         # True when a frame image is supplied for this beat
         "text": str}               # the user's existing rough prompt text ("" if none)
    Beats WITH an image consume vision-call IMAGE slots 1..n in order; the intro states
    the beat -> IMAGE mapping explicitly.
    `enumeration` -- the FIXED reference enumeration composed from pass 1 ("" = no MSR).
    The model writes the GLOBAL as NARRATION ONLY; the caller prepends the enumeration
    (composition, so it can never be dropped or mis-attributed by the writing pass).
    `audio_notes` -- optional list of plain-text lines describing imported audio clips
    (context only; the model cannot hear them).
    `motion` / `camera` / `audio` -- the three orthogonal axes (see axes.py). The inert
    defaults ("free"/"free"/"full") inject nothing; other choices inject their directive
    block in the CLI's exact order: motion core, MSR block, camera, audio, locked rules.
    `hint` -- THE USER'S BRIEF: stated EARLY as the clip's authoritative creative
    direction AND re-stated at the end, outranking the model's own reading of the frames
    and the axis directives; only the output-format rules (and the MSR rules, when
    references are in play) stay absolute. Empty hint injects nothing.
    `global_only` -- write ONLY the GLOBAL prompt (the beats still inform it as context,
    but no SEGMENT sections are demanded -- the panel's "global only" convenience mode).
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
    if not any_image and enumeration:
        lines += [
            "",
            "There are NO beat frames for this clip -- the referenced subjects and scene are",
            "described in the FIXED ENUMERATION below.",
            f"INVENT the {n_segments} story beat(s) yourself: what those referenced subjects do in",
            "the referenced scene, one beat per timeline segment, following THE USER'S BRIEF if",
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

    if global_only:
        lines += [
            "",
            "Your job: write ONE GLOBAL prompt that anchors the whole clip -- subjects, setting,",
            "light, and the overall arc across all the beats above, in present tense, as one",
            "continuous shot (never a scene cut). Segment prompts are handled separately; you",
            "write ONLY the global.",
        ]
    else:
        lines += [
            "",
            "Your job: write the Director prompt set for this clip -- ONE GLOBAL prompt that anchors",
            "the whole clip (subjects, setting, light, overall arc), and ONE SEGMENT prompt per beat",
            "that narrates ONLY what happens inside that beat's window, in present tense, flowing",
            "naturally out of the previous beat and into the next (one continuous shot, never a",
            "scene cut).",
        ]
    hint = (hint or "").strip()
    if hint:
        lines += [
            "",
            "THE USER'S BRIEF (the clip's creative direction -- the finished prompts must",
            "VISIBLY realize this; it OUTRANKS your own reading of the frames and every axis",
            "directive below; only the CRITICAL OUTPUT RULES"
            + (" and THE MSR RULES" if enumeration else "") + " stay absolute):",
            f"  {hint}",
        ]
    intro = "\n".join(lines)

    msr_block = ""
    if enumeration:
        msr_block = (
            MSR_RULES + "\n\n"
            "The references were already READ in a separate pass. The enumeration for THIS clip\n"
            "is FIXED and will be placed at the START of the GLOBAL prompt AUTOMATICALLY:\n"
            f"  {enumeration}\n"
            "Do NOT write or repeat the enumeration yourself -- write the GLOBAL as the NARRATION\n"
            "that follows it. Narrate under rule 7: point at every referenced element by the\n"
            "EXACT look enumerated above (never a name), so the reference tokens bind to your\n"
            "prompt entities.\n\n"
        )

    # Axis blocks, in the CLI's exact order: motion core first, then MSR, then camera and
    # audio (placed after the core so they override any camera/audio the core implies).
    # The inert defaults are all empty strings -- a free/free/full run injects nothing.
    core = MOTION_CORES[motion]
    core_block = f"{core}\n\n" if core else ""
    camera_block = CAMERA_CORES[camera]
    audio_block = AUDIO_DIRECTIVES[audio]

    seg_labels = "" if global_only else (
        "\n".join(f"SEGMENT {i}: <present-tense paragraph for beat {i}'s window ONLY>"
                  for i in range(1, n_segments + 1)) + "\n")
    task = (
        "\n\nNOW WRITE THE DIRECTOR PROMPT"
        + ("" if global_only else "S")
        + ". Output ONLY "
        + ("this labeled section" if global_only else "these labeled sections")
        + ", each label at the start of its own line, exactly:\n"
        "GLOBAL: <one flowing paragraph anchoring the whole clip"
        + (" -- the NARRATION that follows the fixed enumeration, never the enumeration itself"
           if enumeration else "")
        + ">\n"
        + seg_labels
        + "No preamble, no JSON, no headings beyond "
        + ("that label" if global_only else "those labels")
        + ", no bullets. Strictly ASCII."
    )
    brief_reminder = ""
    if hint:
        brief_reminder = ("\n\nREMEMBER THE USER'S BRIEF -- every prompt must visibly "
                          f"realize it:\n  {hint}")
    return (f"{intro}\n\n{core_block}{msr_block}{camera_block}{audio_block}"
            f"{LOCKED_RULES}{task}{brief_reminder}")


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
