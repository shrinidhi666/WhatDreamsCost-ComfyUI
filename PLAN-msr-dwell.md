# PLAN — MSR reference dwell: frame counts past 65 (the V2 4-subject fix)

Branch: `msr-fix`. STATUS: PROPOSED — awaiting sign-off.

## Proven ground truth (2026-07-18 A/B, this machine)
- The V2 LoRA drops/deforms ONE of 4 subjects at frame_count 65 (2 latent blocks per
  subject) — in OUR Director AND in the pure official pipeline (distilled ckpt, stock
  gemma, LiconMSR + LTXAddVideoICLoRAGuide + PromptRelayEncode). Different subject per
  seed = binding threshold, not positional, not port code.
- V1 tolerates 2 blocks; the official V2 demo only ever shows 2 subjects (5+3 blocks).
- Upstream's 65 ceiling is a DROPDOWN choice, not a model/VAE limit: reference clips are
  ordinary 8n+1 videos; the allocator/VAE math continues unchanged above 65.

## The fix
Give every subject >= 3 latent blocks by allowing longer reference clips.

1. `ltx_director_guide.py` — `MSR_FRAME_COUNTS` extends with the 8n+1 series:
   `(17,25,33,41,49,57,65,73,81,89,97,105)`. Values >65 are OUR extension (documented
   as such in the comment; upstream caps its dropdown at 65). `_load_msr_panel`
   validation picks the new values up automatically.
2. `ltx_director_guide.py` — the silent guide truncation
   (`msr_guide_latent = msr_guide_latent[:,:, :latent_length]`) becomes a HARD error
   (upstream asserts; we raise ValueError naming the fix: lower frame_count or lengthen
   the clip). No silent reference loss, ever.
3. `js/ltx_director.js` — dropdown gets the same values; `_msrAutoFrameCount` becomes
   the dwell rule instead of flat 41: `fc = 8*(3*subjects)+1` (= 3 blocks per subject
   + 1 scene block): 1 subj=25, 2=57, 3=81, 4=105; scene-only=17. Manual override unchanged.
   Stale "sample uses 41 with 5 refs" comment corrected.
4. `README.md` — MSR frame-count section rewritten around blocks-per-subject: the
   allocation table, "V2 wants >=3 blocks/subject; 4 subjects -> 97 or 105", the >65
   extension flagged as ours, and the video-must-be->=frame_count rule (now enforced).

## Not in scope
Reference sharpness (2K refs) = user's asset regeneration, no code. AI-Prompt camera
bug = task #2, parked.

## Verify
Hermetic: allocator maps for 73..105 (3+ blocks/subject at the new counts); truncation
error fires when video < frame_count; JSON/JS sanity. Live (user): 4 penguins @97 on
the Director, 2-3 seeds — all four present = fix confirmed; then merge msr-fix.
