# PLAN v2 — MSR as an additive track inside the LTX Director (composable with everything)

Branch: `feat/msr-track` (off `main` @ `9cdbcf0`, clean).
Fork: `git@github.com:shrinidhi666/WhatDreamsCost-ComfyUI.git`.

STATUS: IMPLEMENTED on this branch. DESIGN REVISION (user decision): the msr_* IMAGE ports on the
Guide were removed — the Director's MSR panel (timeline_data.msr) is the SINGLE source for MSR
references (subjects, background, frame count). The Guide keeps only the model/sampling-side
knobs: msr_lora_name, msr_lora_strength, msr_attention_strength. One path, no duplication.
Hermetic + execute-level tests pass (mock VAE: pass-through byte-identical, panel injection
appends 3 latent frames with crop metadata + keyframe_idxs, guardrails raise). Remaining: the
LIVE verification matrix below (user-launched, GPU free), then merge to main.

## Goal
MSR (1–4 subject refs + background) as a fully **additive, optional** track in `LTXDirectorGuide`,
composable à la carte with ALL other Director features:
- prompt relay (local prompts / attention rail)
- image keyframes (first / mid / last frames, timeline image track)
- motion / depth-map / pose / canny videos (IC-LoRA motion track)
- audio (Director AV path)
No MSR inputs connected → the node behaves byte-identically to today.

## Ground truth (verified in code + the official sample, not assumed)

1. **The official Licon-MSR sample workflow ALREADY mixes MSR with prompt relay and audio.**
   `ComfyUI-Licon-MSR/LTX-2.3_MSR_sample_workflow_V2.json` contains, in ONE generation:
   `LiconMSR` (4 subjects + bg) → `LTXAddVideoICLoRAGuide` (frame_idx=0, strength=1,
   latent_downscale_factor=1, crop=center) + `PromptRelayEncode` (WhatDreamsCost's own relay!) +
   `LTXVEmptyLatentAudio`/`LTXVConcatAVLatent`/`LTXVSetAudioRefTokens` (audio). So MSR + relay +
   audio coexistence is officially sanctioned, not our experiment.

2. **MSR reference placement**: frame_idx **0**, strength **1**, downscale factor **1** (from the
   MSR LoRA's `reference_downscale_factor` metadata — verified in the file). ldf=1 → no dilation,
   no grid-snap effect.

3. **LoRAs chain.** `_load_lora_model_only` (ltx_director_guide.py:98) uses
   `comfy.sd.load_lora_for_models`, which returns a patched clone — calling it again with a second
   LoRA stacks the patches. So the depth/union control LoRA (motion track) and the MSR LoRA can
   BOTH be applied to the same model.

4. **Per-guide downscale factors already exist mechanically.** Motion segments encode + dilate with
   THEIR factor (`_encode_video_iclora_guide` takes it as a parameter, line 121; dilation at 592–596).
   Nothing forces one global factor per run — today's single `latent_downscale_factor` variable is
   just how it happens to be wired. MSR's factor is 1, so its guide needs no dilation at all.

5. **Audio is orthogonal.** The Guide node never touches audio; it flows through the Director / AV
   latent path. Zero interaction with MSR.

6. **Tracks are à la carte** (`ltx_director.py:765–769` — relay falls back gracefully; image and
   motion loops each iterate over possibly-empty lists).

## Design

### New inputs on `LTXDirectorGuide` (widgets only — NO image ports; single path = the panel)
- `msr_lora_name`: combo `["None"] + loras`, default "None" — the Licon-MSR LoRA, **separate slot**
  from `ic_lora_name` so depth-video (union control, rdf=2) and MSR (rdf=1) can run together.
- `msr_lora_strength`: FLOAT, default 1.0.
- `msr_attention_strength`: FLOAT 0–1, default 1.0 (same rail as image/video attention strengths).
- `msr_resize_method`: combo [crop, stretch to fit, pad, pad green], default **crop** — how each
  reference is fitted to the video's aspect (crop = the official sample's behavior, no distortion).
- Subjects, background and frame_count come ONLY from the Director's MSR panel via
  `timeline_data.msr` (the `msr_subject_1..4`/`msr_background`/`msr_frame_count` ports of the
  first draft were REMOVED — one path, no duplication).

### Track-gated LoRA loading (LoRAs used ONLY when their track has content)
- `ic_lora_name` is applied **only if** the timeline has guides (images/motion/retake)
  (previously it loaded whenever model+name were set, even with an empty timeline — fixed here:
  same "additive" principle).
- `msr_lora_name` is applied **only if** the MSR panel has a background + ≥1 subject.
- Both present → chain: `model → ic_lora → msr_lora` (order: control first, identity second;
  chaining order of summed LoRA patches is mathematically commutative in ComfyUI).
- Neither track used → model passes through untouched.

### MSR-only must work (found a blocking gate — fix required)
Requirement: **MSR + prompt relay alone** (no image keyframes, no motion video) is a valid run —
this mirrors the official sample exactly. But `ltx_director_guide.py:482` gates ALL guide
processing on `if len(images) > 0 or len(segments) > 0:` — with an empty timeline the block is
skipped entirely and MSR would never inject. Fix: the gate becomes
`if len(images) > 0 or len(segments) > 0 or msr_active:` (prompt relay is unaffected either way —
it rides the conditioning built in the Director, not this gate).

### MSR guide path (reuses the existing rail end-to-end)
1. `_build_msr_guide(subjects, background, width, height, frame_count)` — LiconMSR's compositor
   (resize each to target, stack, expand frames) copied into the fork with attribution. Target size =
   stage resolution (`latent_width*32 × latent_height*32`), matching the sample's "MSR at output
   resolution" usage.
2. Encode via the existing `_encode_video_iclora_guide` with **msr's** downscale factor (1).
3. Inject via `nodes_lt.LTXVAddGuide.append_keyframe` at **frame_idx=0, strength 1.0** —
   exactly the official sample's placement.
4. Register attention entry (`_append_guide_attention_entry`) with `msr_attention_strength`.
5. Run the MSR injection BEFORE the image-guide loop so keyframes/motion order is unchanged
   relative to today.

### Per-track factors
- Motion segments keep using the ic_lora factor (2 for union/depth) for encode + dilation.
- MSR guide uses the msr_lora factor (1): full-res encode, no dilation.
- `auto_snap_ic_grid` keeps snapping on the ic factor only (msr factor 1 is a no-op by definition).
- The `latent_downscale_factor` RETURN output keeps reporting the ic (motion) factor — unchanged
  downstream contract.
- `is_lora_active` (gates attention entries on image guides) becomes "ic OR msr active".

### Guardrails (all in `_load_msr_panel` / execute — panel is the single source)
- Panel has subjects without a background (or a background without subjects) → clear ValueError
  (mirrors LiconMSR:31–32).
- A panel image file missing from the input folder → ValueError (a silent black reference would
  quietly destroy the identity lock).
- MSR refs set but `msr_lora_name` == "None" → hard warning in the log (guide without its LoRA
  degrades output); do not silently proceed as if fine.
- `msr_lora_name` selected but no MSR refs on the panel → LoRA not applied (track-gating), info log.

### What stays exactly as-is
- Image keyframes (first/mid/last) — untouched; optional as today via the timeline.
- Depth/pose/canny motion videos — untouched; still driven by `ic_lora_name` + timeline video track.
- Prompt relay, audio, retake mode — untouched.
- Downscale factors — still auto from metadata; never a user widget.

## Honest caveat (to verify live, not assume)
Running BOTH IC-LoRAs at once (depth control + MSR identity in the same generation) is mechanically
sound (patches sum) but the two LoRAs were not trained together — quality of the combination is
empirical. Each one alone + all other tracks is proven (official sample / existing motion track).
The live verification matrix below covers both cases.

## Stage 2 — MSR UI in the Director (after Stage 1 verifies)
**Design change from v1: an MSR PANEL, not a timeline track.** MSR is not temporal — the
references apply to the whole clip, so a draggable timeline segment is the wrong metaphor and
would drag in the fragile segment machinery (drag/drop/trim/split/playhead) for nothing.

Instead: a compact MSR panel on the Director node — 5 drop/click slots (Subject 1–4 + Background,
thumbnails when filled) + a frame-count selector + a LoRA indicator. All the plumbing already
exists and gets reused, verified in code:
- **Upload**: same ComfyUI upload endpoint the timeline already uses (`handleImageUpload` flow,
  `js/ltx_director.js` ~3921–3984 stores the server `imageFile` path on the object).
- **Serialization**: add `msr: { subjects: [imageFile…], background: imageFile, frameCount }` to
  the existing `timeline_data` JSON. Nothing else in the timeline format changes.
- **Python read**: `LTXDirectorGuide.execute` ALREADY parses `timeline_data` (line 343–348). Load
  the files with the same pattern as `_load_image_tensor` (`ltx_director.py:394` — input-folder
  path, base64 fallback) and feed `_build_msr_guide`.
- **Single source**: the panel is the ONLY way to supply MSR references (the draft's IMAGE-port
  precedence scheme died with the ports — user decision: one path, no confusion).
This keeps Stage 2 additive JS (a panel + serialize) instead of surgery on the segment engine.
`msr_lora_name` stays a node widget (LoRA picking belongs on the node, like `ic_lora_name`).

## Verification (LAW #1 — check GPU free before any live run)
1. Hermetic: `python -m py_compile ltx_director_guide.py __init__.py`; import module.
2. Deterministic: `_build_msr_guide` with 2 dummy subjects + bg @ 736×1280, fc=17 →
   shape [17, 1280, 736, 3]; frame split matches LiconMSR `_expand_frames`.
3. Inert-path proof: `execute` with NO msr inputs → outputs identical to `main` (structural diff).
4. Track-gating proof: msr_lora selected + no msr images → model object unchanged (no patch applied).
5. Live matrix (user-launched, GPU free):
   a. **MSR ONLY + prompt relay** — empty timeline (no image keyframes, no motion video).
      Proves the line-482 gate fix; mirrors the official sample inside the Director.
   b. MSR + image keyframes (first/mid/last frame stills) + audio.
   c. MSR + depth-map motion video (both LoRAs chained) — the empirical case.

## Rollback
Additive + optional throughout. Revert = drop the branch. `main` untouched until merge.

## Resolved (was "open questions" in v1)
- Reference input: the Director's MSR PANEL is the single source (`timeline_data.msr`). The v1
  answer was individual IMAGE ports; those were built, then REMOVED by user decision once the
  panel landed — one path, easier to maintain, no port/panel precedence rules.
- Strength: separate `msr_lora_strength` + `msr_attention_strength` (MSR now has its own LoRA slot,
  so reusing `ic_lora_strength` would couple it to the depth LoRA — wrong).
