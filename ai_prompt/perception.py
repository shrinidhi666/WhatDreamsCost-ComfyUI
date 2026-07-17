"""perception.py -- the AI Prompt's perception stage: turn timeline media into the raw
materials for vision calls. Extraction only, no LLM calls (enhance.py orchestrates those)
-- stdlib + the ffmpeg binary, importable standalone like the rest of ai_prompt.

Empirically established transport (tested 2026-07-17 on Ollama 0.32 + gemma4 12B):
  - audio rides base64 in the same `images` array as pictures (Ollama's only media rail);
    dedicated audio/video fields are ignored and raw video files are not routed.
  - video therefore travels as frames WE extract. Gemma 4's own native video handling is
    1 fps sampling (model card), so frames are not an approximation of native input --
    they ARE the native signal, and we can sample DENSER than native for short beats.
  - one modality per call: frames of one video together, audio always alone. Mixing
    frames + audio in one call loses the audio ~50% of the time (tested).

Extraction is IN-MEMORY (ffmpeg pipes) -- no temp files, no disk churn.

Documented model contracts (Gemma 4 model card,
https://ai.google.dev/gemma/docs/core/model_card_4):
  - audio input: max 30 seconds  -> longer clips are perceived in explicit <=30s windows
    (every second still heard -- chunking, never truncation).
  - video input: max 60s at 1 fps -> we hard-error past 60 frames rather than silently
    thinning the sampling (LAW: no silent downsampling, ever).
"""

import base64
import math
import subprocess

# Perception call defaults. Thinking OFF is the tested default: 10-90x faster with the
# load-bearing quality intact (verbatim speech, quiet audio, scene detail); the panel's
# "deep read" toggle turns it on for label-critical passes.
AUDIO_WINDOW_SECS = 30.0     # model-card audio contract
MAX_VIDEO_FRAMES = 60        # model-card video contract (60s @ 1 fps)
_FFMPEG_TIMEOUT = 120

# Frame sampling: enough frames to SEE motion. 1 fps missed a slow 5s zoom in testing;
# 8 frames over the same window caught it. Short beats sample denser (up to 4 fps so a
# quick action lands on multiple frames); long clips fall back to the native 1 fps.
_TARGET_FRAMES = 8
_MAX_FPS = 4


class PerceptionError(ValueError):
    """A clean, user-displayable perception failure (ffmpeg missing, contract hit)."""


def frames_fps(duration_secs):
    """The sampling rate for a clip of this length: ceil(8/duration) clamped to [1, 4]."""
    if duration_secs <= 0:
        raise PerceptionError(f"Cannot perceive a clip of {duration_secs}s.")
    return max(1, min(_MAX_FPS, math.ceil(_TARGET_FRAMES / duration_secs)))


def _run_ffmpeg(args):
    try:
        proc = subprocess.run(["ffmpeg", "-v", "error"] + args,
                              capture_output=True, timeout=_FFMPEG_TIMEOUT)
    except FileNotFoundError:
        raise PerceptionError(
            "ffmpeg was not found on PATH -- it is required for video/audio perception.")
    except subprocess.TimeoutExpired:
        raise PerceptionError("ffmpeg timed out while reading a media file.")
    return proc


def _split_jpegs(stream):
    """Split an mjpeg image2pipe stream into individual JPEG byte blobs (SOI..EOI)."""
    frames, i = [], 0
    while True:
        s = stream.find(b"\xff\xd8", i)
        if s < 0:
            break
        e = stream.find(b"\xff\xd9", s + 2)
        if e < 0:
            break
        frames.append(stream[s:e + 2])
        i = e + 2
    return frames


def extract_frames(video_path, trim_start_secs, duration_secs):
    """Sample `duration_secs` of the video starting at `trim_start_secs` into JPEG frames,
    in memory. Returns (list of base64 frames, fps used). Hard-errors past the 60-frame
    model contract instead of thinning the sampling."""
    fps = frames_fps(duration_secs)
    expected = math.ceil(duration_secs * fps)
    if expected > MAX_VIDEO_FRAMES:
        raise PerceptionError(
            f"Video window of {duration_secs:.1f}s needs {expected} frames at {fps} fps, "
            f"over the model's {MAX_VIDEO_FRAMES}-frame contract (60s at 1 fps). Split the "
            f"segment or trim the clip; refusing to silently drop frames.")
    proc = _run_ffmpeg(["-ss", f"{max(0.0, trim_start_secs):.3f}",
                        "-t", f"{duration_secs:.3f}", "-i", video_path,
                        "-vf", f"fps={fps}", "-f", "image2pipe", "-c:v", "mjpeg",
                        "-q:v", "2", "-"])
    frames = _split_jpegs(proc.stdout or b"")
    if not frames:
        raise PerceptionError(
            f"ffmpeg produced no frames from '{video_path}' "
            f"({(proc.stderr or b'').decode('utf-8', 'replace')[:300]}).")
    return [base64.b64encode(f).decode("ascii") for f in frames], fps


def extract_audio(video_path, trim_start_secs, duration_secs):
    """The clip's own soundtrack for the window, as one base64 mp3 (mono 44.1k) -- or None
    when the file has no audio stream / the window is silent-empty."""
    proc = _run_ffmpeg(["-ss", f"{max(0.0, trim_start_secs):.3f}",
                        "-t", f"{duration_secs:.3f}", "-i", video_path,
                        "-vn", "-ac", "1", "-ar", "44100", "-b:a", "128k",
                        "-f", "mp3", "-"])
    if proc.returncode != 0 or not proc.stdout:
        return None
    return base64.b64encode(proc.stdout).decode("ascii")


def audio_windows(duration_secs, window=AUDIO_WINDOW_SECS):
    """Explicit <=30s perception windows covering the WHOLE clip: [(start, length), ...].
    Chunking, never truncation -- every second is heard."""
    if duration_secs <= 0:
        return []
    out, start = [], 0.0
    while start < duration_secs:
        out.append((start, min(window, duration_secs - start)))
        start += window
    return out


def file_audio_b64(audio_path, start_secs, length_secs):
    """One perception window of a standalone audio file, base64 mp3."""
    b64 = extract_audio(audio_path, start_secs, length_secs)
    if b64 is None:
        raise PerceptionError(f"Could not read audio from '{audio_path}'.")
    return b64


# ---- Reading prompts (perception only; the tested wordings) ---------------------------

def beat_image_reading_prompt():
    return (
        "Describe this frame concisely and accurately for a film crew: every figure and"
        " what visibly tells it apart (attire, colours, build, pose), key objects and"
        " props, the setting, and the light. Plain visual English, no proper names, no"
        " mythological labels. Describe only what is actually shown. One tight paragraph,"
        " no preamble.")


def video_reading_prompt(n_frames, fps, duration_secs):
    return (
        f"You are given a {duration_secs:.1f} second video as {n_frames} frames sampled at"
        f" {fps} frame(s) per second, in time order (frame 1 = 0.0s). Describe exactly"
        " what happens, concisely and accurately, in time order: every subject and what it"
        " does, the setting, the camera's framing and movement across the frames, and how"
        " the shot ends. Note any visible text or labels. Describe only what is actually"
        " shown. One tight paragraph, no preamble.")


def audio_reading_prompt():
    return (
        "Listen to this audio clip and describe exactly what you hear, concisely and"
        " accurately, in the order it occurs: any speech (quote the words verbatim, note"
        " the voice's character and tone), any music (instruments, mood, tempo), ambient"
        " sound and sound effects. Describe only what is actually audible. One tight"
        " paragraph, no preamble.")
