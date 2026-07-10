"""
routes.py -- the ComfyUI glue for the AI Prompt feature: one endpoint,
POST /ltx_director/ai_prompt, called by the Director's AI Prompt panel.

This module is the ONLY place ai_prompt touches ComfyUI (server / comfy /
folder_paths); the core logic in enhance.py stays importable standalone.

The VRAM ballet (a local Ollama vision model and ComfyUI's video models share
one GPU, so strictly one at a time):
  1. REFUSE while the ComfyUI queue is running or non-empty -- never race a
     generation.
  2. Evict ComfyUI's cached models through the OFFICIAL path: the
     prompt_queue "unload_models" flag (the same mechanism as the UI's unload
     button and POST /free), processed immediately by the prompt worker
     thread -- model ops stay on the thread that owns them. We then poll
     until the loaded-model list is empty and VRAM has actually been handed
     back (torch frees cached blocks a beat after the unload).
  3. Run the Ollama call in a worker thread (it can take minutes; the aiohttp
     event loop must not block). The call carries keep_alive=10s, so Ollama
     evicts ITSELF moments after responding -- by the time the user reviews
     the prompts and hits Queue, the GPU is clean again.
"""

import asyncio
import time

from aiohttp import web
from server import PromptServer

import comfy.model_management
import folder_paths

from . import enhance
from .ollama_client import OllamaError

# How long to wait for ComfyUI to hand the GPU back before calling Ollama anyway
# (Ollama tolerates partial VRAM by offloading layers; a stale wait would be worse).
_EVICT_TIMEOUT_SECS = 15.0
_EVICT_POLL_SECS = 0.5


def _queue_busy():
    q = PromptServer.instance.prompt_queue
    try:
        return q.get_tasks_remaining() > 0
    except Exception:
        running, pending = q.get_current_queue()
        return bool(running) or bool(pending)


def _evict_comfy_models():
    """Ask the prompt worker to unload all models (official flag path), then wait until
    the loaded-model list empties and free VRAM stops growing. Returns a note string for
    the response meta ("" when fully clean)."""
    PromptServer.instance.prompt_queue.set_flag("unload_models", True)
    deadline = time.monotonic() + _EVICT_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if not comfy.model_management.current_loaded_models:
            break
        time.sleep(_EVICT_POLL_SECS)
    else:
        return "ComfyUI models did not fully unload in time; Ollama may need to offload."

    # Models are gone; give the torch allocator a moment to actually release VRAM
    # (the worker runs gc + empty_cache right after the unload flag).
    last_free = -1.0
    while time.monotonic() < deadline:
        try:
            free = comfy.model_management.get_free_memory()
        except Exception:
            break
        if free <= last_free:   # stopped growing -- released as much as it will
            break
        last_free = free
        time.sleep(_EVICT_POLL_SECS)
    return ""


def _run_blocking(payload):
    note = _evict_comfy_models()
    result = enhance.run(payload, folder_paths.get_input_directory())
    if note:
        result.setdefault("meta", {})["vram_note"] = note
    return result


@PromptServer.instance.routes.post("/ltx_director/ai_prompt")
async def ai_prompt(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Body must be JSON."}, status=400)

    if _queue_busy():
        return web.json_response(
            {"error": "ComfyUI is generating. Wait for the queue to finish, then try again."},
            status=409)

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _run_blocking, payload)
    except (ValueError, OllamaError) as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        print(f"[LTXDirector] AI Prompt failed: {e}")
        return web.json_response({"error": f"AI Prompt failed: {e}"}, status=500)
    return web.json_response(result)
