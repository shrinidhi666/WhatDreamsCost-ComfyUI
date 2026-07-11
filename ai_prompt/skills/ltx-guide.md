# LTX 2.3 -- General Prompting Guide (world-neutral, any image)

> **PURPOSE.** A WORLD-NEUTRAL reference on how the LTX 2.3 video model actually behaves, fed to
> the LLM on every motion-prompt run so it writes prompts that get WHAT WE WANT out of LTX. It
> contains NO project/world/brand content and NO subject-specific look -- only how the MODEL
> works. It applies to ANY image or images (one frame or two), any world, any subject. The
> project/world supplies its own look, cast and voices separately (worlds/<name>.json); this file
> supplies the MODEL KNOWLEDGE that is the same for every project.

> **ASCII ONLY in every prompt.** Straight quotes `"` and `'` only (never curly), `--` for dashes
> (never em/en dash), `...` for ellipsis (never the glyph), no accented or Unicode characters.
> LTX and downstream tooling expect plain ASCII; smart punctuation pasted from Word/Docs/Notion
> corrupts prompts. Verify before sending.

---

## 0. LTX 2.3 GENERATES VIDEO + AUDIO TOGETHER -- including SPEECH, in one pass

This is the defining capability and you should prompt to use it fully:

- LTX 2.3 is a **joint audio-visual model**: an asymmetric dual-stream diffusion transformer that
  **generates the video AND its audio in a SINGLE pass**, modelling true joint dependencies
  (NOT a sequential text-to-video-then-add-audio pipeline).
- The audio it generates natively includes **ambient sound, sound effects, music, AND spoken
  DIALOGUE / VOICE** -- and the model **synthesizes the speech itself, directly from the text
  prompt**, with "natural cadence, accent, and emotional tone", lip-synced to the character's
  mouth. **You do NOT need a separate TTS step for the voice** -- the prompt drives it.
- How it works (so the LLM trusts the capability): a dedicated **causal Audio VAE** compresses
  mel-spectrograms into a 1D audio latent and a HiFi-GAN vocoder decodes back to 24 kHz waveform;
  **bidirectional cross-attention** between the video and audio streams locks lip motion to the
  spoken words. The text encoder produces **separate conditioning for the video vs the audio**
  from the same prompt -- so describing the voice in the prompt genuinely shapes the generated
  voice, not just the lips.
- In ComfyUI this is the LTX 2.3 audio path with the **audio VAE** (e.g. `LTX23_audio_vae`)
  loaded alongside the video VAE; the workflow emits a soundtrack (speech + ambient + SFX)
  generated jointly with the frames, not dubbed on afterward.

**Implication for prompting:** WRITE THE AUDIO. Spoken lines, accent, vocal quality, ambient bed
and SFX in the prompt all actually come out in the render. Audio is a first-class part of the
prompt, not an afterthought.

(Note: ComfyUI also offers IMAGE+AUDIO->VIDEO and lip-dub LoRA workflows where you SUPPLY a voice
clip and LTX lip-syncs to it -- useful when you must reuse an exact pre-recorded/cloned voice.
But for prompt-driven generation, LTX synthesizes the voice from your text directly. Pick the
path per shot; this guide covers the prompt-driven path.)

---

## 1. PROMPT ANATOMY -- one flowing present-tense paragraph

Official Lightricks guidance: write the prompt as a **single flowing paragraph**, **present
tense** throughout, and **match the level of detail to the shot scale** (a close-up legitimately
runs longer and finer than a wide). **Longer, detailed prompts consistently outperform short
ones** -- there is NO fixed word cap; detail SCALES with shot type, never a hard count.

**Match prompt LENGTH to video DURATION.** A 10-word prompt for a 10-second clip leaves the model
without enough direction to fill the time -- a longer clip needs a fuller prompt. Under-writing a
long shot is a common failure. The official working target: **roughly 4 to 8 descriptive
sentences** to cover all the key aspects of a typical clip (scale up for longer/closer shots).

**Iterate.** LTX is built for fast experimentation: the official guidance is to START SIMPLE and
LAYER instructions across runs -- the more actions/characters/instructions stacked into one
prompt, the higher the chance some are dropped. First get the core beat right, then add.

**Image-to-Video: do NOT re-describe the static elements already visible in the image.** Describe
the MOTION, the camera, the lighting CHANGE and the AUDIO -- not what the still already shows. Re-
stating fixed visible details wastes the prompt and can fight the input frame.

A complete LTX prompt covers, woven into prose (not bullets in the actual prompt):

1. **Shot / framing** -- camera scale and angle (section 2).
2. **Subject + scene** -- who/what is in frame and the setting, as concrete VISUAL facts taken
   from the image(s). Describe what is actually shown; do not invent identity or lore. When there
   is NO image to lean on (text-only / invented beats), DEFINE each character concretely: age,
   hairstyle, clothing, distinguishing details -- and express emotion through physical cues.
3. **The MOTION** -- the single clear thing that animates over the clip (section 3).
4. **Camera move** -- what the lens does (section 4).
5. **Lighting / mood** -- via physical light description, NOT emotion labels (section 5).
6. **Audio** -- ambient bed + SFX + (if speaking) the spoken line and voice (sections 0 and 6).

LTX 2.3 has a **much larger text connector** than earlier versions, so complex prompts (multiple
subjects, spatial relationships, stylistic instructions) resolve accurately. Be specific; vague
prompts waste that capacity.

---

## 2. SHOT / FRAMING -- name the camera scale explicitly

Use real cinematography terms; LTX honours them. Match detail density to scale.

| Term | Use for |
|------|---------|
| Extreme close-up (ECU) | An eye, a hand, a product detail, a reaction |
| Close-up (CU) | Emotional beats, a speaking face, small-object focus |
| Medium shot | Character interaction, dialogue (speaker + listener) |
| Wide / establishing | Locations, group reveals, setting the geography |
| Over-the-shoulder | Conversation POV |
| Low angle | Power, grandeur, scale |
| High angle / overhead | Vulnerability, vastness, top-down layouts/maps |

Close-ups need MORE descriptive detail (surface, texture, micro-expression); wides need
geography and composition over fine surface detail.

---

## 3. MOTION -- the heart of an LTX clip: ONE clear arc

LTX animates best with **one dominant, legible motion** that has a shape, not many simultaneous
actions.

- **Present tense, as it unfolds:** "the figure raises a hand, then turns toward the door" --
  not "a figure who will turn".
- **Give it an ARC:** setup -> main move -> a peak/beat -> settle. Even a 2-5s clip reads better
  with a beginning-middle-end than one uniform action.
- **Anchor what should NOT move**, phrased POSITIVELY ("the body stays grounded in its pose, only
  the head turns") -- negatives are weak (section 8).
- **TWO-frame (image-to-video):** given a START frame and an END frame, the motion IS the
  difference between them -- identify exactly what changed (position, expression, light, object
  state) and describe the single transition from frame 1 to frame 2.
- **ONE-frame:** invent the natural continuation of what the still SETS UP -- the motion implied
  by the pose, the moment, the held tension.

---

## 4. CAMERA -- describe the lens move as its own clause

State what the CAMERA does separately from subject motion: "slow push-in", "gentle dolly around
the group", "locked medium, no movement", "slow pull-back to reveal". ONE move per clip. A
micro-shake adds life; avoid stacking pan + zoom + dolly in a short clip (it muddies). For
dialogue, a locked or very gently moving camera holding both speaker and listener is usually
right -- big moves fight the intimacy.

For a TRANSLATIONAL move (dolly in, dolly out / pull-back, orbit), name the DESTINATION of the
move and what it REVEALS: describe what lies at the end of the shot and what slides into frame as
the camera travels (the far side of the room, the figures at the edges, the new face of the
subject an orbit uncovers). Giving the model this "map" of where the move arrives and what becomes
visible is the single biggest lever on how well it executes the camera. Prefer LTX's own camera
words -- "dolly in", "dolly out", "dolly left / right", "jib up / down", "pan", "tilt", "orbit" --
which the model reads most reliably.

Official framing of the same rule: describe the CAMERA'S RELATIONSHIP TO THE SUBJECT, and include
how subjects/objects appear AFTER the camera motion so the model knows how to finish the move.
The official camera vocabulary (all read reliably): **follows, tracks, pans across, circles
around, tilts upward, pushes in, pulls back, overhead view, handheld movement, over-the-shoulder,
wide establishing shot, static frame.**

---

## 5. LIGHTING / MOOD -- physical light, never emotion labels

Set mood through described LIGHT, not adjectives like "sad" or "tense". Name source, direction,
colour, quality: "dim golden backlight, deep shadows, volumetric god-rays"; "hard low directional
light, dust in the air"; "soft pink-orange dawn, cool blue shadows, mist on water". LTX renders
light; it does not render the word "ominous". Let the light imply the feeling.

Official visual-detail vocabulary (use as levers, not a checklist):
- **Lighting conditions:** flickering candles, neon glow, natural sunlight, dramatic shadows,
  backlighting, soft rim light, flickering lamps, golden hour.
- **Textures:** rough stone, smooth metal, worn fabric, glossy surfaces.
- **Color palette:** vibrant, muted, monochromatic, high contrast.
- **Atmospheric elements:** fog, rain, mist, dust, particles, smoke, reflections -- weather and
  atmosphere GROUND a scene and are a named LTX strength.

---

## 5b. STYLE / AESTHETIC -- name it EARLY in the prompt

Stylized aesthetics work especially well **when named early in the prompt** (painterly, noir,
analog film look, fashion editorial, pixelated animation, surreal). Official style vocabulary:

- **Animation:** stop-motion, 2D animation, 3D animation, claymation, hand-drawn.
- **Stylized:** comic book, cyberpunk, 8-bit pixel, surreal, minimalist, painterly, illustrated.
- **Cinematic:** period drama, film noir, fantasy, epic space opera, thriller, modern romance,
  experimental film, arthouse, documentary.
- **Film characteristics:** jittery stop-motion, pixelated edges, lens flares, film grain.
- **Scale indicators:** expansive, epic, intimate, claustrophobic.
- **Pacing / temporal effects:** slow motion, time-lapse, lingering shot, continuous shot,
  dynamic movement, sudden stop. (Official examples also use rapid cuts / freeze-frame /
  fade-in / fade-out -- valid for LTX generally, but in a segment/relay pipeline each prompt is
  ONE continuous shot, so keep cut/fade language OUT of per-segment prompts.)
- **Visual effects (when relevant):** particle systems, motion blur, depth of field.

LTX's named strengths to lean on: cinematic compositions with shallow depth of field; **emotive
single-subject human moments** (subtle gestures, facial nuance); atmosphere/weather grounding;
clean readable camera language; early-named stylized aesthetics; physical lighting anchors.

---

## 6. AUDIO -- describe it fully; 2.3 generates it from the prompt

Because LTX 2.3 generates audio jointly (section 0), spend real attention here:

- **Ambient bed:** room tone, wind, water, crowd, machinery -- the place's natural sound.
- **SFX, time-aligned:** the specific sounds events make ("a match strike", "an engine rev", "a
  sharp impact boom", "a soft bell tone") -- LTX syncs these to the matching motion.
- **Music:** only if wanted, described plainly ("a low building drone", "a heroic sting").
- **Spoken dialogue / VOICE:** LTX synthesizes the voice from the prompt -- so describe BOTH the
  WORDS and HOW they sound. See section 7 for the exact pattern. Characters can talk AND SING,
  in various languages.
- **Volume words read reliably:** a quiet whisper, mutters, shouts, screams.
- Official ambience examples: ambient coffeeshop noise, dripping rain and wind blowing, forest
  ambience with birds singing. Official voice-style examples: energetic announcer, resonant
  voice with gravitas, distorted radio-style, robotic monotone, childlike curiosity.

---

## 7. DIALOGUE & VOICE -- LTX speaks the line; write words + voice

Official LTX pattern: **place spoken dialogue in straight double quotes**, **specify language and
accent if needed**, **break long sentences into shorter phrases with acting directions between
them**, and direct the performance with **PHYSICAL CUES, not emotional labels** (write what the
face/body DOES, not "he feels sad"). The model generates that speech, synchronized to the lips, in
the voice you describe. Official example (world-neutral, verbatim shape):

> A middle-aged man with greying hair speaks in a sad, slow-paced voice, "I remember after you kids
> came along..." He pauses and looks to the side, then continues, "your mom..." His eyes widen
> momentarily. He finishes with a cracking voice, "said something to me I never quite understood."

How to write the VOICE:

- **Describe the timbre/quality:** "a resonant low voice with gravitas", "a bright nasal childlike
  voice", "a gravelly distorted radio-style voice", "a breathless cracking near-whisper".
- **Specify accent/language** if it matters to the character (the model handles accent + cadence).
- **Direct delivery with physical cues + pacing** ("slow and deliberate, then pauses", "fast,
  clipped"), breaking a longer line into phrases with physical beats between them so timing and lip
  motion land.
- **Keep the line short** for a short clip -- a 2-5s shot fits a few words, not a paragraph (and
  match the prompt's overall length to the clip's duration).
- **Write each spoken line (or vocalized sound) exactly ONCE.** A character making a sound is BOTH
  seen (the mouth moves) and heard (the audio) -- but quote it only ONE time, as the audio, and
  describe the mouth/beak moving WITHOUT re-quoting the sound. Wrong (doubled): "her beak moves with
  the engine sound, \"Vrooom\" ... she speaks, \"Vrooom\"." Right (once): "she speaks in <voice>,
  \"Vrooom\", her beak moving in sync." This applies to words AND non-word vocalizations (a gasp, a
  laugh, "shh", "Vrooom"): repeating the quoted sound makes LTX utter it twice or mistime it.
- **A spoken line belongs with the BEAT that carries it.** Place each line inline at the moment the
  speaker performs its matching action/gesture (the gesture and its line together, in order) rather
  than collecting all the lines at the end of the paragraph -- this is what lands the lip-sync and
  the timing.
- **Never put a spoken word on the FIRST frame.** LTX's opening instant is unstable -- the audio and
  lip-sync need a moment to lock on, so anything spoken at frame 0 gets clipped or swallowed (it
  fails the SAME way on every seed). Open every dialogue clip with a brief LEAD-IN beat of motion or
  breath with no speech (a lean-in, a drawn breath, a held pose), THEN start the line. The lead-in
  moves the first word out of the dead zone so it lands fully.
- **Supplied-voice / lip-sync path (image+audio->video):** the SAME first-word clip hits the AUDIO you
  feed in. Trim any head/tail silence on the voice clip, then add ~150 ms of silence at the HEAD so the
  opening word is not swallowed; deliver the VO as 48 kHz mono WAV at roughly -16 LUFS (gentle comp,
  minimal noise reduction). The prompt lead-in beat (above) plus this audio head-pad together stop the
  first-word loss on every seed.

**Voice CONSISTENCY across shots (same character sounds the same in every clip):** describe the
SAME voice the SAME way every time -- the voice description should be a fixed, reusable property
of the CHARACTER (stored per-project / per-world, not re-improvised per shot). Reuse the identical
voice phrasing for that character in every prompt so the generated voice stays consistent across
the whole series. (If you need an EXACT pre-recorded/cloned voice instead, use the ComfyUI
image+audio->video / lip-dub path and supply that audio -- section 0.)

---

## 8. WHAT TO AVOID (official "don't" list)

The official guide names specific things that DEGRADE an LTX prompt -- keep them out:

- **Internal emotional states / emotion labels** ("she is sad", "he feels tense"). Show it with
  PHYSICAL cues -- face, posture, light -- not the feeling word.
- **Text, logos, lettering in the scene.** LTX renders text poorly; do not ask for words/logos to
  appear in frame. (A product/brand showing is a render/compositing concern, not an LTX text
  request.)
- **Complex physics** (intricate collisions, fluid/cloth simulation chains, precise mechanical
  cause-and-effect). Keep motion physically simple and legible. Fast non-linear / fast-twisting
  motion (jumping, juggling) is artifact-prone -- **dancing, however, works well**.
- **Overloaded scenes** -- too many subjects/actions at once. One dominant subject and one
  dominant motion read far better than a crowded prompt. The official cure is ITERATION: begin
  simple, layer instructions on across runs (section 1).
- **Conflicting lighting** -- do not describe two incompatible light setups in one shot
  (e.g. "a warm sunset with cold fluorescent glow") unless the mix is clearly motivated.
- **Vague prompts** -- "be specific and descriptive"; describe the FULL scene (subject, action,
  environment, lighting, camera, audio) in cinematic language professionals understand.

---

## 9. NEGATIVES are weak -- prompt POSITIVELY

LTX responds far better to what you DO want than to "no X". Instead of "no camera shake", write
"the camera is locked and still". Instead of "she does not move her body", write "her body stays
grounded in its pose, only her eyes shift". If your node has a negative field, keep it short and
generic; carry the real intent in the positive.

---

## 10. QUICK CHECKLIST (does this prompt get what we want?)

- [ ] Single flowing paragraph, present tense; prompt length matched to clip duration + shot scale
      (~4-8 descriptive sentences for a typical clip).
- [ ] Style/aesthetic (if any) named EARLY in the prompt.
- [ ] Subject/scene taken from the image(s); nothing invented beyond what is shown. (I2V: do NOT
      re-describe static elements already in the frame.)
- [ ] Shot scale + angle named explicitly.
- [ ] ONE dominant motion with an arc; held-still phrased positively.
- [ ] ONE camera move, stated as its own clause.
- [ ] Mood set by PHYSICAL light, not emotion words.
- [ ] Audio written fully: ambient + time-aligned SFX; music only if wanted.
- [ ] Any spoken line: quoted, broken into short phrases with beats, WITH a described voice; the
      same character's voice described identically every shot for consistency.
- [ ] Strictly ASCII punctuation.
- [ ] No world/brand/subject content baked into anything reusable -- that comes from the
      project/world config, not this guide.

---

## Sources

- LTX-2 official repo README (ltx-core) -- https://github.com/Lightricks/LTX-2/blob/main/packages/ltx-core/README.md
- LTX-2 Technical Report (joint audio-visual, audio VAE, vocoder) -- https://videos.ltx.io/LTX-2/grants/LTX_2_Technical_Report_compressed.pdf , https://arxiv.org/pdf/2601.03233
- LTX-2.3 official prompt guide -- https://ltx.io/model/model-blog/ltx-2-3-prompt-guide
- LTX-2 official prompting guide (blog: structure, 4-8 sentences, style-early, vocabulary banks,
  sing/languages, dancing-vs-jumping, iterate) -- https://ltx.io/blog/prompting-guide-for-ltx-2
- LTX-2.3 model overview -- https://ltx.io/model/ltx-2-3
- LTX-2.3 Day-0 support in ComfyUI (enhanced audio-video) -- https://blog.comfy.org/p/ltx-23-day-0-supporte-in-comfyui
- LTX-2.3 image+audio->video in ComfyUI (Next Diffusion) -- https://www.nextdiffusion.ai/tutorials/ltx-2-3-image-to-video-with-custom-audio-in-comfyui
- LTX 2.3 Audio VAE model (Kijai) -- https://ltxworkflow.com/models/ltx23-audio-vae
- LTX-2.3 image+audio->video workflow (comfy.org) -- https://comfy.org/workflows/video_ltx2_3_ia2v-adca306765ce/
