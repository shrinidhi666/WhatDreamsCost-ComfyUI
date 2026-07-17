# PLAN — MSR V2 prompt convention for the AI Prompt feature (+ scene-only panels)

Branch: `main` (fork `git@github.com:shrinidhi666/WhatDreamsCost-ComfyUI.git`).
Scope: the AI Prompt layer ONLY (`ai_prompt/prompt_builder.py`, `ai_prompt/enhance.py`) plus the
two user-facing doc surfaces that state the old contract (`README.md`, one tooltip in
`js/ltx_director.js`). The Guide node / compositor (`ltx_director_guide.py`) is ALREADY V2-correct
(subjects optional, background required, frame counts 17–65) and is NOT touched. `ltx-guide.md`
is a pure LTX 2.3 guide — MSR never appears in it and never will (user law: do not mix).

STATUS: APPROVED 2026-07-17 — executing. Everything MSR-V2 is fixed IN THIS REPO: the AI
Prompt convention (sections 1-2), the scene-only gate (section 3), the docs (sections 4-5).
No other repo is touched by this plan.

## Why (ground truth, verified 2026-07-17 against primary sources)

The AI Prompt's MSR rulebook was vendored from vector-lab `director_ltx.py` on 2026-07-10 —
the **V1** convention. The official V2 release changed the prompt contract. Read from the
sources directly:

1. **LiconMSR node source + README** (`ComfyUI-Licon-MSR/licon_msr.py`): subject slots `1`–`4`
   are ALL optional (`_expand_frames` explicitly supports zero subjects — every frame = the
   background); `background` is the ONE required input. So: **0–4 subjects + 1 required scene**,
   not "1–4 + 1".
2. **Official V2 sample workflow** (`LTX-2.3_MSR_sample_workflow_V2.json`, V2 LoRA,
   PromptRelayEncode node — the strongest prompt-format source):
   - `global_prompt` = the reference enumeration ONLY: one line per reference,
     "图 N：<concise look>" (= "Image N: …"), subjects first, scene last, **no "(scene)" tag** —
     and nothing else. No narration in the global.
   - the narration lives in `local_prompts` and refers to every referenced entity **by its
     TOKEN** (图1/图2 = "Image 1"/"Image 2") at every mention — staging, action, and dialogue
     attribution. **Bind-by-token replaces V1's bind-by-look.**
   - camera CUTS between shots of the one scene are used freely and stated explicitly
     (cut to a close-up of 图2, a two-shot, an over-the-shoulder).
   - the narration opens with a spatial anchor: scene light/layout, then who stands where,
     wearing what, by token.
3. **Model card** (huggingface.co/LiconStudio/LTX-2.3-Multiple-Subject-Reference): V2 improves
   consistency/stability/scene-logic; "concise but accurate" descriptions; no format mandate —
   the sample carries the format.

vector-lab `director_ltx.py` was already rewritten to this V2 contract (commit `f02acf2` in the
comfy-jsons repo). This plan brings the node's vendored copy back in sync.

## Changes

### 1. `ai_prompt/prompt_builder.py`
- **`MSR_RULES`** — replace the V1 block with the V2 rulebook (re-vendor from `director_ltx.py`,
  vendor date bumped). Substance identical to the CLI; the examples are adapted to this node's
  etched punctuation law (no hyphens/parentheses/colons in generated output: "close up",
  "frame left", speech written as `Image 1 says in a hoarse mumble, "..."`). Rule 7 carries ONE
  extra sentence the CLI does not need: *for referenced entities the token replaces the
  point-by-look rule (LOCKED_RULES); figures NOT on the reference panel are still pointed at by
  look and frame position* — this resolves the only conflict between the V2 convention and the
  node's locked output rules, at the rules level, not with a scrubber.
- **`format_enumeration()`** — emits the V2 shape: `Image N: <clause>.` lines, scene last with
  NO "(scene)" tag, newline-joined (the sample's exact global shape). Same composition-by-code
  design (pass 1 unchanged).
- **`LOCKED_RULES`** — the colon exception names the new label (`"Image N:"`).
- **The MSR job text** (`msr_enum_shape` branch) — GLOBAL stays an EMPTY section (the fixed
  enumeration is prepended by code, as today); ALL story in the segments, narrated by token
  (rule 7); segment 1 opens with the spatial anchor (rule 9); camera cuts allowed and stated
  explicitly (rule 8) replacing "one continuous shot, never a scene cut" on MSR runs only.
  The V1 instruction "point at each referenced subject by a SHORT distinguishing handle drawn
  from its enumerated look" is deleted — that is the retired binding.
- **Both `bind_note`s** — "point by the EXACT look enumerated (never a name)" → "refer to every
  referenced entity by its token, Image N, at every mention".
- **`global_spec`** (task section) — the enum-shape line says: leave GLOBAL empty, the fixed
  enumeration IS the global.
- **PLACEHOLDER NAMES for the brief (the user's original request)** — a new block in the MSR
  section of the pass-2 prompt, mirrored from `director_ltx.py`: the USER'S BRIEF may address a
  reference by a placeholder — "subject N" / "sub N" / "subN" / "reference N" / "ref N" /
  "refN" / "reference image N" (any casing) = enumeration entry N; "scene" / "background" /
  "bg" / "subbg" = the scene entry. The number is ALWAYS the enumeration/panel number. Resolve
  the name, apply the direction to that entity, and write it in the output as its canonical
  token "Image N". So a brief of "sub1 is the father, sub2 is the mother" binds roles to the
  right references. Injected only when an enumeration exists (inert otherwise); the subject
  aliases are stated only when subjects exist, the scene aliases only when relevant.
- **Stale-global detection** — `startswith("Reference image 1:")` becomes
  `startswith(("Reference image 1:", "Image 1:"))`: workflows saved under BOTH conventions
  exist on disk; both prefixes are a regenerated enumeration, not user intent.
- **Image-less + enumeration intro wording** — "what those referenced subjects do in the
  referenced scene" → covers the zero-subject case ("what happens in the referenced scene, and
  what the referenced subjects, if any, do there").
- Docstring/comment lines that state the old convention (module header pass-1 line,
  `MAX_MSR_SUBJECTS` comment, `msr_enum_shape` comment) restated to V2.

### 2. `ai_prompt/enhance.py`
- **`collect_msr_refs()`** — the contract change at its origin: background REQUIRED, subjects
  OPTIONAL. Empty panel → `([], 0)` as today; background missing (with subjects present) →
  ValueError; **background alone → valid** `([bg], 0)`. Error message states the real contract.
- **Pass-1 gate in `run()`** — `if msr_count:` → `if ref_images:` so a scene-only panel still
  gets its reference read (subject loop naturally runs zero times; the scene read at
  `ref_images[msr_count]` is index 0 — correct).
- **Enumeration prepend** — `f"{enumeration} {global_prompt}"` → newline-joined, preserving the
  V2 line shape in the composed global.
- Docstrings stating "Reference image N:" restated to V2.

### 3. `ltx_director_guide.py` — ONE line (verified necessary, 2026-07-17)
`_load_msr_panel` already allows a subjects-less panel (background required, subjects
optional), but the track activation at line 517 contradicts it:
`msr_active = msr_background is not None and len(msr_subjects) > 0` — a scene-only panel
loads, then silently deactivates the whole MSR track (no LoRA, no guide injection).
Fix at the origin of the decision: `msr_active = msr_background is not None`. Everything
downstream (LoRA gating, guide build, attention entry, `is_lora_active`) keys off
`msr_active` and needs no change; `_build_msr_guide`/`_expand_msr_frames` already handle
zero subjects (all frames = background, mirroring upstream `_expand_frames`).

### 4. `README.md` (MSR / AI Prompt section)
- The example enumeration (lines ~219–220) rewritten to the V2 shape (`Image 1: …` /
  `Image 2: …`, no "(scene)" tag) with a token-bound narration line.
- "the LoRA is only applied when the panel has a background + at least one subject" (line ~233)
  → background required, subjects optional. NOTE: this also requires the track-gating condition
  in `ltx_director_guide.py` IF it still demands a subject — verified: `_load_msr_panel` already
  says "subjects optional" and only requires the background; no Python change needed there.

### 5. `js/ltx_director.js`
- MSR panel tooltip (line ~4069): "Needs at least one subject AND a background" → "Needs a
  background (scene) reference; subjects optional (up to 4)". Tooltip text only — the panel
  logic already serializes whatever is filled.

## What stays exactly as-is
- The two-pass architecture (pass 1 reads each ref alone; pass 2 writes; code composes) — it is
  V2-compatible by design and is the node's proven shape.
- `parse_sections`, `allow_empty_global`, the labeled-sections hard-error contract.
- LOCKED_RULES / PERCEPTION_RULES beyond the two lines named above.
- The Guide node, compositor, LoRA gating, panel serialization, `ltx-guide.md`, all skills.

## Verification
1. Hermetic: `py_compile` both files; module-load `prompt_builder` (stub package context);
   `format_enumeration` for (2 subjects + scene) and (scene only) → exact expected text;
   `build_vision_prompt` for subjects+bg, bg-only, and no-MSR → V2 rules present / absent
   correctly, retired V1 strings absent; `parse_sections` round-trip with empty GLOBAL.
2. Live (user-launched, GPU rules apply): one AI-Prompt run in the Director with 2 subjects + bg
   → GLOBAL is the pure enumeration, segments narrate by `Image N`; one run with bg only.

## Rollback
Single commit; revert = `git revert` it. Nothing else depends on the changed strings.
