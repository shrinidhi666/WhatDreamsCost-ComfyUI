# PLAN — Ingredients mode: 8-slot panel, auto-composed cached sheet, official prompting

Branch: `msr-fix`. STATUS: PROPOSED — awaiting sign-off.

## Ground truth (researched 2026-07-18)
Lightricks' first-party `LTX-2.3-22b-IC-LoRA-Ingredients` (`ltx-2.3-22b-ic-lora-ingredients-0.9
.safetensors`) conditions on ONE composite reference SHEET — clean panels (characters, props,
location) on a BLACK background, no text — looped as a static video and fed through
`LTXAddVideoICLoRAGuide` (frame 0, strength 1, factor 1, crop disabled). No per-subject frame
allocation exists, so the V2-MSR "one subject starved and dropped" mechanism cannot occur.
Official stack = `ltx-2.3-22b-dev` + `distilled-lora-384 @0.5` (the user's existing stack) +
ingredients LoRA (card recommends strength 1.4; official workflow ships 1.0). Prompt = two
sections: `### Reference Sheet Description` (each panel by POSITION and TYPE) then
`### Target Description` (narration binding subjects BY LOOK). 121+ frames, trained bucket
768x448@24fps (official workflow runs 960x544).

## Step 0 — prove it on their content (before any node code)
Compose the 4-penguin + desert sheet on CPU (panels on black, video aspect), write the
two-section prompt, patch the official example workflow with both (same drill as the MSR A/B).
User downloads the LoRA, queues 2-3 seeds. All four penguins hold -> build the feature.

## The feature (Director node)
1. **Panel: 8 subject slots + the background slot** (same drop/click UX as today; "sub1..sub8").
   MSR mode still caps at 4 (upstream contract); slots 5-8 error under MSR.
2. **Mode = the selected LoRA file** (root fact, no new toggle): `msr_lora_name` containing
   `ingredient` -> ingredients path; otherwise the existing MSR path (V1 etc.) unchanged.
3. **Auto-composed sheet, cached**: Python-side grid compositor — video-aspect-aware layout
   (rows x cols chosen for the slot count; location gets its own panel; refs fitted WHOLE on
   BLACK, never cropped, no text). Cache key = sha256 of (slot file list + mtimes + video WxH
   + layout version) -> sheet PNG in ComfyUI temp; reused byte-identical while nothing changes.
4. **Feed** (existing IC rail): sheet looped to the video's latent length, LTXVPreprocess(18),
   inject frame 0 / strength 1 / factor 1 / crop disabled, CropGuides after sampling —
   mirroring the official workflow node-for-node.
5. **AI Prompt: ingredients convention** — pass 1 reads each slot image individually (existing
   one-image-per-call reads); CODE composes `### Reference Sheet Description` with the REAL
   panel positions from the compositor's own grid (Top Row Left (Character): ... — code knows
   the layout, the model never guesses); the GLOBAL prompt carries that section plus the
   `### Target Description` header; SEGMENTS narrate by LOOK (not tokens — this LoRA's
   convention). MSR-mode prompting (Image N tokens) untouched.
6. **Docs**: README section; PLACEHOLDER aliases (sub1..sub8) keep working in the brief —
   resolved to "the subject in panel <position>" for look-binding.

## Verify
Hermetic: compositor grid for 1..8(+bg) slots at 16:9 / 9:16 (all panels whole, black bg,
cache hit/miss behavior); prompt assembly carries both sections; MSR path byte-unchanged when
an MSR LoRA is selected. Live: step 0 first; then the same 4 penguins through the Director in
ingredients mode, 2-3 seeds.
