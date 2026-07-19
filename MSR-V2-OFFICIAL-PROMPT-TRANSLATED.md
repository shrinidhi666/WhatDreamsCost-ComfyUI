# The official Licon-MSR V2 sample prompt — full English translation + pattern anatomy

Source: `F:\ComfyUI\custom_nodes\ComfyUI-Licon-MSR\LTX-2.3_MSR_sample_workflow_V2.json`,
PromptRelayEncode node 180. This is the ONLY official V2 prompt in existence (no English
sample was ever published). Translated word-for-word 2026-07-18.

## GLOBAL (the enumeration — this is the ENTIRE global prompt)

Original:
```
图 1：醉酒，红脸的男人，短发，凌乱金丝眼镜，灰西装，污渍领带，醉态，实拍自然质感。
图 2：女子，黑发盘髻，透明眼镜，深蓝便利店制服，实拍自然质感。
图 3：夜间罗森便利店收银台货架冷柜入口，实拍自然质感。
```

English:
```
Image 1: drunk, red-faced man, short hair, messy gold-wire glasses, grey suit, stained tie,
drunken demeanor, live-action natural texture.
Image 2: woman, black hair in a coiled bun, clear glasses, dark-blue convenience-store
uniform, live-action natural texture.
Image 3: night-time Lawson convenience store — checkout counter, shelves, cold cabinets,
entrance, live-action natural texture.
```

## LOCAL (the narration — one segment)

English, faithful:
```
Night-time Lawson convenience store interior, the checkout counter brightly lit, shelves and
cold cabinets neatly arranged, deep night outside the glass door, color temperature warm-white
leaning cold, camera axis locked, side-front medium shot. Image 1, wearing the crumpled grey
suit, stands at frame left in front of the checkout counter, body swaying slightly, cheeks
flushed red, tie loose. Image 2, wearing the dark-blue convenience-store uniform, stands at
frame right behind the counter, both hands holding the barcode scanner, brow slightly
furrowed, facing Image 1. Shelves and cold cabinets extend into the background.

Image 1's body sways left and right, one hand bracing the counter, speech halting.
Image 1 (murmuring, hesitant and probing, hoarse voice): "I... I want... that... water..."

The camera cuts to a close-up of Image 2, single-person shot. Her gaze is nervous, leaning
slightly forward. Image 2 (urgently, soft and soothing, gentle voice): "Are you alright?
Would you like to sit down first?"

The camera cuts back to a two-person medium shot, two-person shot. Image 1 sways again,
almost failing to steady himself. Image 1 (choking, halting, breathy voice): "It's fine...
I... can still... walk..."

The camera cuts to an over-the-shoulder, two-person shot. Image 2 reaches out a hand to
support him, stops in mid-air, eyes full of worry. Image 2 (exhorting, earnest, gentle
voice): "Don't rush, I'll get it for you." The counter's fluorescent tube hums faintly;
outside the door the night is silent.
```

## PATTERN ANATOMY — every device in the sample

1. GLOBAL = enumeration ONLY. One line per reference, subjects first, scene last.
2. EVERY enumeration line ends with the SAME style tag ("live-action natural texture").
3. Token form: `图 N：` (space + full-width colon) in the enumeration; `图N` (no space)
   inline in the narration. NOTE: the tokens are the CHINESE characters — the LoRA's
   training captions presumably used 图N literally; English "Image N" is an untested
   translation (candidate cause of binding inconsistency; being A/B-tested).
4. The narration OPENS with a dense SPATIAL ANCHOR: scene, light, color temperature,
   "camera axis locked" + shot size, then each subject with token + FUSED look + frame
   position + micro-state (swaying, flushed, tie loose).
5. FUSED token+look at the staging mention ("Image 1, wearing the crumpled grey suit");
   later mentions may be bare (Image 1's body sways) once staged.
6. EVERY camera cut declares its PERSON COUNT: "single-person shot", "two-person shot" —
   the anti-mixing device.
7. Dialogue: Image N (manner, tone, voice-type): "line" — attribution carries voice
   direction, line quoted once.
8. Closing ambience: one sound line grounding the scene (hum + silence).

## The verified working recipe on this machine (2026-07-18)
- LoRA: LTX-2.3-Licon-MSR-V2.safetensors (metadata-less; downscale factor 1)
- Text encoder: STOCK gemma_3_12B_it.safetensors bf16 — the abliterated "heretic" encoder
  breaks reference binding (identity mixes); never use it for MSR runs.
- Frame count: 105 for 4 subjects (>=3 latent blocks each; 65 gives 2 each and drops one).
- Prompting: this document's pattern.
- Any figure NOT on the reference panel must be given its own explicit look, or it
  inherits a reference's design (a scripted bird rendered as a penguin).
