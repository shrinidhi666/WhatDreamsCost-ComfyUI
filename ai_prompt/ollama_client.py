"""
ollama_client.py -- a zero-dependency HTTP client for a local Ollama server.

Stdlib only (urllib + json + base64): the node pack must stay whole with no pip installs
and no imports from any outside project. Talks to Ollama's /api/generate with vision
images, thinking, and keep_alive -- the three things the AI Prompt feature needs.

keep_alive: how long Ollama keeps the model in VRAM after the response. The node default
is "10s" -- long enough to re-click Generate while iterating, short enough that the GPU
is free again moments after you stop, ready for the actual video generation.
"""

import base64
import json
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:11434"
DEFAULT_KEEP_ALIVE = "10s"
DEFAULT_NUM_CTX = 32768
# Vision + a long system skill on a big local model: the first call also pays the model
# load, which can take minutes on a card that needs CPU offload.
REQUEST_TIMEOUT_SECS = 600


class OllamaError(RuntimeError):
    """A clean, user-displayable Ollama failure (connection, HTTP, or empty output)."""


def file_to_b64(path):
    """Read an image file and return its base64 string (Ollama's images[] format)."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def data_url_to_b64(data_url):
    """Strip a browser data-URL ('data:image/jpeg;base64,....') down to the bare base64
    payload Ollama expects. A bare base64 string passes through unchanged."""
    s = (data_url or "").strip()
    if s.startswith("data:"):
        comma = s.find(",")
        if comma == -1:
            raise OllamaError("Malformed data URL for an image (no comma).")
        s = s[comma + 1:]
    return s


def _post_json(url, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = str(e)
        raise OllamaError(f"Ollama HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise OllamaError(
            f"Cannot reach Ollama at {url} ({e.reason}). Is the Ollama server running?") from e


def check_server(base_url=DEFAULT_URL):
    """Return the Ollama server version string, or raise OllamaError. A cheap reachability
    probe (loads no model)."""
    url = base_url.rstrip("/") + "/api/version"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("version", "unknown")
    except urllib.error.URLError as e:
        raise OllamaError(
            f"Cannot reach Ollama at {base_url} ({e.reason}). Is the Ollama server running?") from e


def generate_vision(prompt, images_b64, model, system=None, base_url=DEFAULT_URL,
                    temperature=1.0, num_ctx=DEFAULT_NUM_CTX, think=True,
                    keep_alive=DEFAULT_KEEP_ALIVE, timeout=REQUEST_TIMEOUT_SECS):
    """ONE non-streaming vision call: read `images_b64` (list of bare base64 strings) and
    answer `prompt`. Returns the stripped response text. Raises OllamaError on any failure
    or empty output. think=True lets the model reason before writing (the reasoning stays
    internal; only the final response is returned) -- the same shape as the CLI's call."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": bool(think),
        "keep_alive": keep_alive,
        "options": {"temperature": temperature, "num_ctx": int(num_ctx)},
    }
    if system:
        payload["system"] = system
    if images_b64:
        payload["images"] = list(images_b64)   # top-level, NOT inside options
    url = base_url.rstrip("/") + "/api/generate"
    data = _post_json(url, payload, timeout)
    text = (data.get("response") or "").strip()
    if not text:
        raise OllamaError("Ollama returned an empty response. Try again or use another model.")
    return text
