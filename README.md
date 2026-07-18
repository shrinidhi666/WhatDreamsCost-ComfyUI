# Overview

This will be a collection of free resources for ComfyUI.

Hopefully it will make creating cool stuff easier!

Also if you want to support this project or my channel, I did make a Ko-fi due to popular demand lol (anything helps!)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/J5N221K0D5)

> **🔱 About this fork** ([shrinidhi666/WhatDreamsCost-ComfyUI](https://github.com/shrinidhi666/WhatDreamsCost-ComfyUI), forked from [WhatDreamsCost](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI) — all original nodes and credit belong to the upstream author). This fork adds to the LTX Director:
> - **MSR (Multi-Subject Reference)** — lock up to 4 subject identities + a background across the whole clip via the official Licon-MSR LoRA ([details](#-msr--multi-subject-reference-this-fork))
> - **AI Prompt** — a built-in prompt generator: one click writes the global + per-segment prompts from your timeline images/videos and MSR references using a local Ollama vision model ([details](#-ai-prompt--generate-the-prompts-from-the-timeline-this-fork))
> - **Per-image Guide Strength that actually works** — each keyframe's strength now controls how strongly the model follows *that* image ([details](#-per-image-guide-strength-this-fork))
> - **Track-gated LoRAs** (the IC/MSR LoRA is only applied when its track has content), a **Clear All** button, and assorted guardrails

## ▶️ YouTube Tutorial Videos

<table>
  <tr>
    <td>
      <p align="center">LTX Director 2.0 Trailer</p>
      <a href="https://www.youtube.com/watch?v=o0l6Ikvn5Q0">
        <img src="https://img.youtube.com/vi/o0l6Ikvn5Q0/0.jpg" alt="LTX Director Trailer" width="400">
      </a>
    </td>
    <td>
      <p align="center">LTX Director 1.0 Tutorial</p>
      <a href="https://www.youtube.com/watch?v=vM60pJJqqEI">
        <img src="https://img.youtube.com/vi/vM60pJJqqEI/0.jpg" alt="LTX Director Tutorial" width="400">
      </a>
    </td>
  </tr>
</table>

## ❓ How to install nodes

- Navigate to your `/ComfyUI/custom_nodes/ folder`
- Run `git clone https://github.com/WhatDreamscost/WhatDreamsCost-ComfyUI`
- Or download through the ComfyUI Manager.

**❗❗IMPORTANT❗❗**

If you don't see the latest version (v1.3.9) yet in the manager then just download the nightly version (or fetch the updates to update the list to see the latest version). 
Also you will need to update ComfyUI-LTXVideo and ComfyUI-KJNodes to the latest version as well. You cannot use this node without updating ComfyUI-LTXVideo!

# 🔄 Recent Updates

**Fork — AI Prompt: built-in prompt generator (local Ollama)**
* One click writes the **global prompt + one prompt per timeline segment** from your actual timeline (keyframes, video first-frames, MSR references) with a local Ollama vision model. Hint/brief box, motion/camera/audio dropdowns, per-beat placement, GPU-safe (ComfyUI models are unloaded first; the Ollama model frees the GPU seconds after answering). See the AI Prompt section below.

**Fork — per-image Guide Strength now steers for real**
* Each keyframe's Guide Strength is now applied to that image's **attention** (the channel that actually guides LTX 2.3), not just the legacy noise mask. Defaults unchanged; `image_attention_strength` on the Guide becomes a master fader. See the section below.

**Fork — MSR (Multi-Subject Reference) support**
* The LTX Director gets full **Licon-MSR** integration: an MSR panel on the Director (up to 4 subject identity references + a background) plus `msr_*` controls on the LTX Director Guide node, composable with every other Director feature (prompt relay, keyframes, audio, IC-LoRA motion). See the **MSR — Multi-Subject Reference** section under LTX Director 2.0 below for the LoRA download link and usage.

**v2.0.0**
* **Massive Update to LTX Director. I will add the full list of changes later.**

  - **Complete Video Support:** Edit Videos with AI all inside the node. Videos can be extended using a combination of prompts, keyframes, and audio. Trim, Split, and combine videos all within the timeline.

  - **IC-LoRA Support:** Take full advantage of IC-LoRA's to take your generations to the next level. Simply drag and drop videos onto the IC-LoRA track to quickly setup IC-LoRA videos. Compatible with prompt relay, keyframe, and custom audio features within the node.

  - **Audio Inpainting:** Seamlessly blend imported audio with generated audio. Not only can audio be extended, but can also be prompted alongside your imprted audio to really bring your generations to life.

  - **Retake Mode (Beta):** Redirect what happens within a shot. Allows you to select a segment within a video, and re-generate what happens in that segment. An early working experiment.

  - **Timeline Saving/Loading:** You can now save your timeline and settings to a json file. It will keep any videos/audio/images you have imported into the node and every setting you have changed.

  - **UI Overhaul:** Huge update to the UI, dozens of big changes such as a new side bar, redesigned prompt boxes, a bunch of new settings and redesigned menus, and more.

  - **Quality of Life Improvements:** Snapping, in/out points, multi-select, mark selection, workspace folder, more HUD options, resizable prompt boxes, new hotkeys, labels, filename preview options, "split at playhead" functionality, end frames (convert any keyframe into a end/last frame), toggleable tracks, NAG Support, tons of bug fixes and more!


**v1.3.9**
  * **Fixed recent updates not showing in the manager**

It took like 5 tries but I finally got it working 🤦‍♂️

**v1.3.3**
  * **LTX Director Hotfix 2**
    - Fixed duration_seconds input issue.
    - Made both duration widgets visible at all times now
    - Implemented audio latent fix to improve compatibility


**v1.3.2**
  * **LTX Director Hotfix**
    - Fixed epsilon input overlapping custom_width input
    - Fixed invisible widgets in nodes 2.0 when toggling widget visibility through settings menu

If anyone finds anymore bugs or has idea for improvements please let me know! 


**v1.3.1**
  * **LTX Director Example Workflow Fix**
    - Minor fix to the example workflow (i forgot to set the clip loader type to ltxv lol)


<details>
  <summary>Click to view older Updates</summary>
    
 **v1.3.0**
  * **New nodes: LTX Director and LTX Director Guide**
    - A complete timeline editor that can do almost everything. It's my most ambitious node so far and the successor to LTX Sequencer/Multi Image Loader.

 **v1.2.9**
  * **Fixed every known issue with Multi Image Loader and added text output to Speech Length Calculator**
  
    - Removed the completely useless drag and drop animations (now it's snappy and no longer finicky)
    - Fixed the node resizing on nodes 2.0 
    - Updated grid logic to fit images better
    - Added ablity to right click images to copy/open/save images
    - Fixed the "invisible hitbox" underneath node issue (actually this time).

  Also added a text output to the Speech Length Calculator node (can't believe i didn't do this initially)
  
 **v1.2.8**
  * **Updated Load Video UI and Color Conversion**
    * Added crop mode, a simple interface to crop videos. It also include various aspect ratio presets.
    * Updated color conversion to ensure colors are as accurate as possible. Will first check metadata for colorspace, and if metadata is missing then it will guess the colorspace based on video dimensions.
    * Updated display mode toggle UI to be more understandable 

 **v1.2.7**
  * **New Node: Load Video UI**

Custom Node to Trim, Resize, and Preview Videos in Realtime
  
   **v1.2.6**
  * **Updated Speech Length Calculator UI**

Also added duration output to the Load Audio UI node

 **v1.2.5**
  * **Updated Load Audio UI Node**
    * Added Duration Setting
    * Made the whole selection bar draggable
    * Fixed Trimmed UI to show centiseconds
    
 **v1.2.4**
 * **New Node: Load Audio UI**

Overhaul of the load audio node. Features a simple interface to easily trim audio. Also allows dragging and dropping files (fixes the original node that doesn't allow dropping in videos). Also compatible with nodes 2.0.

 **v1.2.3**
  * **Workflow Update + Minor Bug Fix** 
    * Added new workflow that is compatible with the latest ComfyUI version (as of 4/27/26). The new workflow also included an option to include custom audio, and has minor improvements of the previous workflows.
    * Fixed minor bug with Multi Image Loader that blocked mouse input in a small area under the node 🤷‍♂️

**v1.2.0**
  * **New Node: Speech Length Calculator** 
  
  Automatically output in realtime how long a video should be based on the dialouge. 

**v1.1.0**
  * Added resize_method to the Multi Image Loader node for more resize options
  * Added insert_mode which allows you to enter in seconds instead of frames on the LTX Sequencer node
  * Updated workflows with more notes
  * Re-added tiny vae to workflows
  * Fixed various bugs
  * more things i can't rememeber
  
**This update will change the node layouts, so be sure to update your workflows or else they won't work properly.**

❗❗❗ **New Tutorial on using these nodes available: https://www.youtube.com/watch?v=aXDIr8eNovI**  ❗❗❗
</details>

# ⚙️ Custom Nodes


## LTX Director 2.0
<img width="1562" height="870" alt="LTX_Director_Wide" src="https://github.com/user-attachments/assets/e2f9edec-c492-443e-84de-0ad1c0db04b3" />

A Complete Timeline Editor For LTX 2.3. This is the sucessor of my previous nodes, and has loads of features in it. It was originally based off of [Kijai's Prompt Relay node](https://github.com/kijai/ComfyUI-PromptRelay) and my LTX Sequencer/Multi Image Loader nodes.

**Main Features:**
- **Fully Functional Timeline Editor:** I spent hours studying various video editors and ended up with this design. If anyone has ideas for improvements let me know! I will adding documentation on all the functions soon.
- **Prompt Relay integrated:** This unlocks the ability to have granular control over video generation. For more information on Prompt Relay go here, https://gordonchen19.github.io/Prompt-Relay/
- **First, Middle, Last Frame Support:** This has by far the easiest method of creating first/last frames videos. It supports any number of keyframes, and will be the successor of my previous nodes.
- **Custom Audio Support:** Import, trim, and combine your own audio clips in this node. Enabling custom audio is as simple as clicking 1 button. It is also compatible with every other feature in the node, include first/last frames, t2v, i2v, and prompt relay.
- **Image to Video:** Part of the goal of this node was to make it easier to do everything, including Image to Video. It has built in resize functionality, and of course all the benifits of the prompt relay and custom audio integration.
- **Text to Video:** Use text segments to create T2V videos. Compatible with all other features of the node.

**LTX Director 2.0 Update Main Features**
 - **Complete Video Support:** Edit Videos with AI all inside the node. Videos can be extended using a combination of prompts, keyframes, and audio. Trim, Split, and combine videos all within the timeline.

  - **IC-LoRA Support:** Take full advantage of IC-LoRA's to take your generations to the next level. Simply drag and drop videos onto the IC-LoRA track to quickly setup IC-LoRA videos. Compatible with prompt relay, keyframe, and custom audio features within the node.

  Special Thanks to https://nghtdrp.com for vibe coding the inital implementation of IC-LoRA support. 

  - **Audio Inpainting:** Seamlessly blend imported audio with generated audio. Not only can audio be extended, but can also be prompted alongside your imprted audio to really bring your generations to life.

  - **Retake Mode (Beta):** Redirect what happens within a shot. Allows you to select a segment within a video, and re-generate what happens in that segment. An early working experiment.

  - **Timeline Saving/Loading:** You can now save your timeline and settings to a json file. It will keep any videos/audio/images you have imported into the node and every setting you have changed.

  - **UI Overhaul:** Huge update to the UI, dozens of big changes such as a new side bar, redesigned prompt boxes, a bunch of new settings and redesigned menus, and more.

  - **Quality of Life Improvements:** Snapping, in/out points, multi-select, mark selection, workspace folder, more HUD options, resizable prompt boxes, new hotkeys, labels, filename preview options, "split at playhead" functionality, end frames (convert any keyframe into a end/last frame), toggleable tracks, NAG Support, tons of bug fixes and more!

### 🧬 MSR — Multi-Subject Reference (this fork)

Lock the identity of up to **4 subjects + 1 background/scene** across the whole clip, using the official **Licon-MSR IC-LoRA** for LTX 2.3 — fully integrated into the Director, no extra nodes needed.

**The LoRA (required):**
- Download from Hugging Face: [LiconStudio/LTX-2.3-Multiple-Subject-Reference](https://huggingface.co/LiconStudio/LTX-2.3-Multiple-Subject-Reference) — file `LTX-2.3-Licon-MSR-V2.safetensors` (V2: better identity consistency, stability and scene logic; the official V2 sample workflow uses it)
- Put it in `ComfyUI/models/loras/`
- Credits: the LoRA and the official sample workflow are by [LiconStudio](https://github.com/liconstudio/ComfyUI-Licon-MSR)

**How to use:**
1. Click the **MSR** button in the Director's toolbar to open the MSR panel.
2. Drop **exactly one background** (scene) reference — the one required slot — and **0–4 subject** references onto the panel. A background-only panel is a valid scene-only run (locks just the location). A subject reference may itself be a multi-view sheet (the same character from several angles in ONE image) — that's the strongest identity signal.
3. The reference **frame count** sets the length of the composed reference clip (`17 … 105`, always `8 x N + 1` to align to LTX's 8:1 temporal VAE; values above `65` are this fork's extension of the upstream list — same math, longer clip). **The dwell rule (proven 2026-07-18):** each reference occupies whole latent blocks, and the **V2 LoRA drops or deforms subjects that get fewer than ~3 blocks** — verified in this fork AND in the pure official pipeline with 4 subjects at `65` (2 blocks each: one penguin lost per seed). The panel auto-sets the smallest count giving every subject **at least 3 blocks** (the allocator front-loads subject 1): 1 subject = `25`, 2 = `57`, 3 = `81`, 4 = `105` — and stays a manual override. The **video must be at least as long as the reference clip** (the Guide now refuses instead of silently dropping the tail references). Raise the count if identity drifts; lower it to save compute with few subjects.
4. On the **LTX Director Guide** node, select the LoRA in `msr_lora_name` (leave strength at `1.0` to start).
5. The **global prompt** is the reference enumeration and NOTHING else — one tight `Image N:` line per reference, subjects first, scene last (the official V2 convention). The narration lives in the timeline segments and refers to every referenced entity **by its token** (`Image N`) at every mention — staging, action, dialogue:

```
Global prompt:
Image 1: a tall woman with silver hair, a red leather jacket, black boots.
Image 2: a rain soaked neon alley at night.

Segment: Image 1 walks toward the camera through the alley, neon reflections
sliding over the wet ground. The camera cuts to a close up of Image 1 ...
```

**Guide node controls:**
- `msr_lora_name` — the Licon-MSR LoRA. A **separate slot** from `ic_lora_name`, so a depth/pose control LoRA (motion track) and MSR can run together in one generation.
- `msr_lora_strength` — LoRA strength (default `1.0`).
- `msr_attention_strength` — guide-attention strength for the MSR reference tokens, `0–1` (default `1.0`).
- `msr_resize_method` — how each reference is fitted to the video's aspect: `crop` (default — center-crop, no distortion), `stretch to fit`, `pad`, `pad green`.

**Good to know:**
- References can be **any aspect ratio**. With the default `crop` they are center-cropped to the video's aspect — keep each reference's identity carrier (face / subject) centered so the crop never trims it.
- The composed reference guide is injected at frame 0 with strength 1.0 — the official sample workflow's placement.
- MSR is fully **additive and composable**: it works alongside prompt relay, image keyframes (first/mid/last frames), custom + inpainted audio, and IC-LoRA motion videos. With no MSR references on the panel the node behaves exactly as before — the LoRA is only applied when the panel has a background (subjects optional).
- MSR is disabled in Retake Mode.
- From the official model card: identity typically locks within **2–3 seeds**, and high-motion scenes render smoother at **50 fps**.

### ✨ AI Prompt — generate the prompts from the timeline (this fork)

One click writes the **global prompt + one prompt per timeline segment** — grounded in what's actually on your timeline — using a **local Ollama** vision model. Fully self-contained (stdlib HTTP, no extra pip packages, no external tools).

**Requirements:** a running [Ollama](https://ollama.com) server and a vision-capable model (e.g. a large Gemma). Configure once in the node's **Settings menu (gear icon) → AI Prompt (Ollama)**: server URL, **Prompt Model** (writes the prompts), and optionally a **Vision Model** — it's remembered.

**Vision Model (optional perception pass):** set an audio/video-capable model (e.g. `gemma4:12b-it-bf16`) and the AI Prompt actually **watches your timeline videos** (frames sampled densely enough to catch the motion — up to 4/s for short beats), **hears your audio clips and each video's own soundtrack** (transcribed speech, music, tone), and reads images/MSR references — then the Prompt Model writes from those faithful descriptions instead of guessing from a single frozen frame and a filename. One modality per call (the empirically reliable transport); frames are extracted in-memory, nothing touches disk. Clips are perceived whole — long audio in explicit 30s windows, and a video window needing more than 60 frames is a hard error, never a silent thinning. **Deep Read** lets the vision model think during perception (slower; better small-text/label reading). Leave the Vision Model empty and everything behaves exactly as before.

**How to use:**
1. Build your timeline as usual (keyframes / videos / MSR references — any mix, or MSR refs alone).
2. Click **AI Prompt** in the toolbar to open the panel.
3. Optionally type a **brief** ("quiet dusk mood, she notices the camera at the end") — the generated prompts must visibly realize it, and it may introduce elements not in your frames. When you already have prompts on the node (see the fidelity law below), the brief acts as a **director's note over them**: it re-stages and changes what it asks for; everything it doesn't touch stays truthful to your text.
4. Optionally pick **motion / camera / audio** (defaults `free/free/full` let the model decide; other choices inject authoritative LTX-native directives — e.g. `push_in`, `no-music`).
5. Click **Generate**. The global prompt box and every segment's local prompt fill in, beat by beat. Review, tweak, Queue.

**What it knows:** every keyframe image, every video's first frame, the MSR panel references (enumeration-first prompting per the MSR rules), each segment's real time window (used for pacing only — the written prompts never contain timing words), your existing global + segment prompts, and your imported audio clips (as context).

**The fidelity law:** your **existing prompts are the story's ground truth**. The global prompt and any segment text you've written go in and come out the same story — every subject, prop, action, mood and camera idea you stated is kept; only the craft is upgraded (LTX-native phrasing, staging, shot grammar, physical continuity, flow). Invention happens only where your text is silent. Empty brief + existing prompts = pure faithful enhancement; the brief, when present, directs changes on top. (With MSR references, the global stays reserved for the reference enumeration — your existing global's intent is carried into the segment prompts, per the trained MSR pattern.)

**Beats:** the panel's "beats" number is the **total story beats you want for the clip**. Existing segments count as beats; if you ask for more, the uncovered part of the timeline (before/between/after your keyframes) is split into the remaining beats and created as text segments for you. Empty timeline + MSR refs = all beats invented (MSR-only mode).

**GPU safety (single-GPU friendly):** the endpoint refuses while ComfyUI is generating, unloads ComfyUI's models before calling Ollama, and the Ollama model evicts itself ~10 seconds after answering — by the time you review the prompts and hit Queue, the GPU is clean.

### 🎚️ Per-image Guide Strength (this fork)

The per-segment **Guide Strength** you drag on a timeline keyframe now controls how strongly the model **follows that image** — upstream (and every node passing core AddGuide's `strength`) only wires it to a legacy noise mask that LTX 2.3 barely responds to, which is why the slider used to feel dead.

- `1.0` — the video follows that keyframe fully (default; existing workflows behave identically).
- `0.7` — that keyframe pulls at 70%; other keyframes are unaffected.
- `0.0` — that keyframe is skipped entirely.
- `image_attention_strength` on the Guide node acts as a **master fader** multiplied over all keyframes (leave at 1.0 to just use the per-image sliders).
- Active when an **IC or MSR LoRA** is loaded on the Guide (the attention rail belongs to that mechanism); without a LoRA the slider falls back to the legacy behavior.

### 🧹 Quality of life (this fork)

- **Clear All** button — wipes the timeline content (images/videos/text + their prompts, paired audio) and the global prompt with a two-click guard. Settings, standalone audio, IC videos and MSR refs untouched.
- **Track-gated LoRAs** — `ic_lora_name` / `msr_lora_name` are only applied when their track actually has content, so an unused selection never patches the model.

Download workflows here: https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/tree/main/example_workflows

**Tutorial videos and documentation coming soon**


## Multi Image Loader
<img width="1280" height="720" alt="Multi_Image_Loader_Wide_Gif" src="https://github.com/user-attachments/assets/99b6afd8-5197-4e6c-81da-a7bd156c42c7" />

An Image loader that features a built in gallery, allowing your to easily rearrange images and output them seperately or batched together. It also combines the image resize node and LTXVPreprocess node to reduce clutter in LTX workflows.

## LTX Sequencer
![LTX_Sequencer_GIF](https://github.com/user-attachments/assets/88f27155-f50e-4cb2-b937-ab173e6bdf0b)

An overhaul of the LTXVAddGuideMulti node. It allows you to quickly create FFLF (First Frame Last Frame) videos, shot sequences, supports any number of middle frames.

Connect the Multi Image Loader node's multi_output to automatically update the node's widgets.

It also has a sync feature that syncs all LTX Sequencer nodes together in realtime, removing the need to edit every single node manually every time you want to make a change to something. 


## LTX Keyframer
<img width="1082" height="608" alt="LTX Keyframer Wide" src="https://github.com/user-attachments/assets/850ba4a2-dbca-4e5a-a580-1c271e9f0c41" />

An overhaul of the LTXVImgToVideoInplaceKJ node. It allows you to quickly create FFLF (First Frame Last Frame) videos and shot sequences. Also upports any number of middle frames.

Connect the Multi Image Loader node's multi_output to automatically update the node's widgets.

It also has a sync feature that syncs all LTX Keyframer nodes together in realtime, removing the need to edit every single node manually every time you want to make a change to something. 

**I would recommend using the LTX Sequencer Node over this node, after further testing it seems superior in at pretty much everything. I'll leave it in just in case more people want to test it**

## Speech Length Calculator
<img width="1280" height="720" alt="Speech Length Calculator v2 Gif" src="https://github.com/user-attachments/assets/04b9a1cf-20e4-4b7b-a9c6-4a5a0825995b" />
<br>
<br>
This node calculates in realtime how long a video should be based on the dialogue. Any words in quotations will be considered as speech. The node updates in realtime without having to run the workflow, and outputs the length depending on how fast the speech is.

If you connect another string/text node to the text_input, it will still update in the length in realtime.

I kept having to play the guessing game on my own generations so I made this node to make it easier :man_shrugging:

## Load Video UI  
<table width="100%">
  <tr>
    <td width="50%" align="center">
      <p>Simple Controls</p>
      <img src="https://github.com/user-attachments/assets/fb76ff03-a6ff-4837-bd63-7e429f5f3d37" width="100%" />
    </td>
    <td width="50%" align="center">
      <p>New Crop Mode!</p>
      <img src="https://github.com/user-attachments/assets/28cfb4ca-e42a-44da-9afb-f20cb01b9722" width="100%" />
    </td>
  </tr>
</table>

<br>
<br>
An upgraded Load Video node. It has the following features:

* Simple interface to quickly trim videos and preview them in realtime.
* Ability to load any length of video into the node (the default load video node was limited to 100MB files)
* Easily switch between showing seconds and frames with a toggle button. This will change the widgets as well as the interface.
* Multiple options for resizing the video (maintain aspect ratio, crop, stretch to fit, pad)
* Allows dragging and dropping files into the node
* Progress bar
* Optimized to use less RAM (still very limited due to ComfyUI limitations, but at least a little more efficient)

Please note that due to ComfyUI limitations (and the fact that this node doesn't use any addtional libraries), this node will not work well for outputting large videos. You can trim any length of video without a problem, but if the output is still large it will end up using a lot of RAM. I have implemented various optimizations though to make it use less memory.

## Load Audio UI  
<img width="1280" height="720" alt="Load_Audio_UI_V2" src="https://github.com/user-attachments/assets/e3dc5c8d-d0b9-4336-8196-944204719239" />
<br>
<br>
An upgraded Load Audio node. Features a simple interface to easily trim audio. Also allows dragging and dropping files (fixes the original node that doesn't allow dropping in videos). Also compatible with nodes 2.0.

# 💡 Workflows
Download workflows here: https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/tree/main/example_workflows

# ❗ Known Issues

Fixed everything so far. If there are any other issue or bugs you find please let me know!

# 💡 Additional Info

Feel free to suggest improvements, and if you run into any bugs let me know!

For those asking, I mainly used gemini to create these nodes.
