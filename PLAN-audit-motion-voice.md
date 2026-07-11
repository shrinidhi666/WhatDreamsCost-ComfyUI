# PLAN — deep audit + motion control (sparse tracks) + voice/identity clone (ID-LoRA)

Date: 2026-07-11. Status: PLAN ONLY — nothing here is implemented. Every claim below was
verified on THIS machine (packs read, example workflows dissected, LoRA files confirmed on
disk) — nothing is assumed from memory.

---

## PART 1 — CODEBASE AUDIT (ranked)

### P0 — security (same fix pattern for all three: basename + realpath containment)
1. **`/video_ui_upload_chunk` (load_video_ui.py:27) — path-traversal WRITE.** The raw client
   `filename` goes straight into `os.path.join`; a `..\\..\\name` escapes the input folder.
   The Director's own chunk endpoint (ltx_director.py:352) got the sanitization fix; this
   duplicated copy never did — the classic divergence cost of the duplication.
2. **`/ltx_director_get_audio` (ltx_director.py:277) — read traversal.** Raw `filename`
   query joined into the input dir; can probe/read arbitrary paths (peaks/audio extraction).
3. **`/ltx_director_check_file` (ltx_director.py:70) — existence-probe traversal.** Same
   pattern, information leak only.

### P1 — correctness / robustness
4. **Window-listener leak on node deletion** (js): `destroy()` removes keydown/paste but NOT
   the `window.addEventListener("mousemove"/"mouseup", (e) => ...)` pair (ltx_director.js:3152
   — anonymous arrows, unremovable as written). Every deleted/recreated Director leaks two
   permanent listeners bound to a dead editor.
5. **Bare `except:` x7** (load_audio_ui.py:47,56,93; ltx_director.py:416,620,1033,1055) —
   swallow SystemExit/KeyboardInterrupt too; should be `except Exception`.
6. **`get_audio_peaks` runs ON the event loop** in `/ltx_director_get_audio` (audio branch),
   while the video branch correctly uses `run_in_executor` — long audio files stall the whole
   server. Move to executor like its sibling.
7. **commitChanges logs the ENTIRE timeline JSON to the console on every commit**
   (ltx_director.js:9110) — every drag/keystroke prints kilobytes; measurable UI overhead and
   console noise. Delete or gate behind a debug flag.

### P2 — duplication (one fix point each, all previously catalogued, re-verified)
8. Chunk-upload endpoint + `_read_and_write_file_chunk` duplicated (load_video_ui vs
   ltx_director) — fold into one shared helper; the security asymmetry (#1) is the proof of cost.
9. Serializer strip-list duplicated **6x** (js 712/718, 9096/9100, 10508/10512) — one
   `stripRuntimeFields(seg)` helper; any new runtime field currently needs 6 edits.
10. Input-path resolution implemented ~5x across ltx_director.py inline sites, guide's
    `_resolve_input_video_path`, and ai_prompt's `resolve_input_file` — ONE shared resolver
    (with containment) fixes #2/#3 and future call sites at once.
11. `/upload/image` FormData blocks x6, canvas frame-grab blocks x4 (js) — style-level; fold
    opportunistically when touching those functions, not as a dedicated pass.
12. Image-resize semantics duplicated (multi_image_loader hand-rolled vs Director's
    comfy.utils path) — **leave**; consolidating risks changing existing outputs.

### P3 — usability polish (audit-grounded, small)
13. `alert()` x5 for errors (timeline load/save, workspace folder) — replace with the
    status-line pattern the AI panel uses; alerts block the UI thread.
14. MSR button/panel are NOT hidden in Retake Mode (python ignores MSR there and warns) —
    hide like the other content buttons to kill the confusion.
15. `print()` vs `log` mixed across ltx_director/guide (16 prints) — unify on `log`.
16. diag: the queue-busy check in ai_prompt routes is advisory (user can queue between check
    and Ollama call) — acceptable; document as known.

---

## PART 2 — MOTION CONTROL via LTX SPARSE TRACKS (feasibility: CONFIRMED)

### Ground truth (all verified on this machine)
- **Mechanism exists and is installed**: `ComfyUI-LTXVideo/sparse_tracks.py` ships
  `LTXVSparseTrackEditor` (canvas widget: draw Catmull-Rom splines over a reference image ->
  per-frame point samples; `points_to_sample` default 121 = 120 frames + 1) and
  `LTXVDrawTracks` (GPU renderer: coloured dots, age gradient blue->green->yellow->red,
  50-frame trails, radius 2->8, **BGR order to match the IC-LoRA training data**).
- **The control LoRA is already in the loras folder**:
  `ltx-2.3-22b-ic-lora-motion-track-control-ref0.5.safetensors`.
- **Official example** `LTX-2.3_ICLoRA_Motion_Track_Distilled.json`: editor -> DrawTracks ->
  `LTXAddVideoICLoRAGuide` (frame_idx 0, strength 1) + distilled LoRA 0.5 — i.e. the rendered
  track video rides the SAME IC rail the Director's motion track already drives.
- **What it controls**: object/part motion via point trajectories (each spline = one tracked
  point). Camera: coarse drift is achievable by moving many points coherently, but true
  camera moves remain the prompt's / union-control's job — set expectations accordingly.

### Path A — zero code, usable TODAY
Side workflow: LoadImage (your first frame) -> SparseTrackEditor (draw) -> DrawTracks
(width/height = your clip) -> SaveVideo; then drop that video on the Director's motion track
and pick the **motion-track** LoRA in `ic_lora_name`. Constraints: sample points =
duration_frames + 1; render at the clip's aspect (the Guide's resize would distort tracks).

### Path B — integrated "Tracks" mode in the Director (the feature)
1. **Stage T1 — plumbing (python)**: `timeline_data.tracks` = list of splines (control
   points, normalized 0..1 coords + optional per-track start/end frame). The Guide gains
   `_build_track_guide`: vendor `_interpolate_spline` (~50 lines, deterministic) + the
   DrawTracks rasteriser (or import from the installed ComfyUI-LTXVideo with a hard error
   if missing — decide at implementation; vendoring matches the fork's self-contained law),
   render at stage resolution, inject through the EXISTING motion-video path (factor
   auto-read from the LoRA metadata as always). Track-gated like everything else: no tracks
   -> nothing loads. Hermetic test: rendered frames vs the official node's output on the
   same spline JSON — must match.
2. **Stage T2 — UI**: a "Tracks" toggle on the toolbar; in tracks mode, clicks on the
   existing preview canvas add spline control points over the CURRENT frame (per-track
   colour, drag to move, right-click to delete, per-track frame-range = the segment window
   it was drawn in). Serialized like the MSR panel; drawn as an overlay in render().
3. **Stage T3 — live verify**: same seed, tracks on/off; a two-point crossing test (the
   official example's shape) on a real scene; then tracks + MSR (empirical combo, same
   caveat class as depth+MSR — the LoRAs were not co-trained).

---

## PART 3 — VOICE + FACE CLONE via ID-LoRA TalkVid (feasibility: CONFIRMED)

### Ground truth (all verified on this machine)
- **The LoRA is already in the loras folder**: `ltx-2.3-id-lora-talkvid-3k.safetensors`
  (ID-LoRA = Identity-Driven In-Context LoRA: a reference IMAGE + a ~5s reference AUDIO clip
  jointly lock the subject's face AND voice; TalkVid-3K = the LTX-2.3 22B checkpoint).
- **Native core support is installed** (ComfyUI 0.27.1): `LTXVReferenceAudio` in
  comfy_extras/nodes_lt.py — takes model + conditioning + reference_audio (~5s recommended)
  + audio VAE + `identity_guidance_scale` (default 3.0; runs an EXTRA forward pass per step
  to amplify speaker identity — CFG-like cost) + sigma window; `ref_audio` conditioning is
  plumbed through model_base. The LTXVideo pack also has `LTXVSetAudioRefTokens` (speaker
  identity context; used by the Lipdub example with `ic-lora-lipdub-0.9`).
- **Distinct from MSR**: MSR locks VISUAL identity of up to 4 subjects from stills; ID-LoRA
  locks ONE subject's face+voice jointly. Combining them is untrained/empirical.

### Path A — zero code, usable TODAY
In the Director workflow: chain `LoraLoaderModelOnly` (talkvid, 1.0) after the Guide's MODEL
output, then `LTXVReferenceAudio` (model, pos, neg, your ~5s voice clip, audio VAE, scale 3.0)
before the sampler. Face reference = the first-frame keyframe on the timeline. Dialogue in
quotes in the prompts (the AI Prompt button already writes dialogue with acting beats).
Expect ~2x sampling cost while identity guidance is active (extra forward pass).

### Path B — integrated "Voice" slot in the Director
1. **Stage V1**: a Voice slot next to the MSR panel (upload/drop a ~5s clip — the audio
   upload path exists); serialize into `timeline_data.voiceRef`.
2. **Stage V2 (Guide)**: optional `audio_vae` input + `id_lora_name` (default None) +
   `identity_guidance_scale` widgets; when a voice ref is present: load the ID-LoRA
   (track-gated — no voice, no patch, per the fork's gating law), encode the clip with the
   audio VAE, attach ref_audio conditioning + the identity-guidance model patch (vendor
   LTXVReferenceAudio's execute — it is small and core-stable).
3. **Stage V3 — live verify**: same seed with/without voice ref; a dialogue clip in the
   cloned voice; then ID-LoRA + MSR together (empirical), and the cost measurement of
   identity_guidance_scale 3.0 vs 0.

---

## SUGGESTED ORDER (when implementation is approved)
1. P0 security trio + the shared resolver (#10) — one commit, small, closes all traversals.
2. Motion control T1 -> T2 -> T3 (the headline feature; Path A usable immediately while T2 lands).
3. Voice clone V1 -> V3 (Path A likewise usable immediately).
4. P1 items (#4 listener leak, #5 excepts, #6 executor, #7 console spam) — one cleanup commit.
5. P2/P3 opportunistically.

Still open from before: the live MSR verification matrix (a/b/c) + the Guide-Strength A/B —
fold into the T3/V3 live sessions to spend GPU time once.
