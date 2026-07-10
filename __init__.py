from .ltx_keyframer import LTXKeyframer
from .multi_image_loader import MultiImageLoader
from .ltx_sequencer import LTXSequencer
from .speech_length_calculator import SpeechLengthCalculator
from .load_audio_ui import LoadAudioUI
from .load_video_ui import LoadVideoUI
from .ltx_director import LTXDirector
from .ltx_director_guide import LTXDirectorGuide, LTXDirectorCropGuides
from comfy_api.latest import ComfyExtension, io
from typing_extensions import override

# AI Prompt (local Ollama prompt generator for the Director) -- optional feature: the
# import registers POST /ltx_director/ai_prompt; a failure must never break the pack.
try:
    from .ai_prompt import routes as _ai_prompt_routes  # noqa: F401
except Exception as _ai_prompt_err:
    print(f"[WhatDreamsCost] AI Prompt endpoint not registered: {_ai_prompt_err}")

class PromptRelay(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            LTXDirector,
            LTXDirectorGuide
        ]

async def comfy_entrypoint() -> PromptRelay:
    return PromptRelay()
    
NODE_CLASS_MAPPINGS = {
    "LTXKeyframer": LTXKeyframer,
    "MultiImageLoader": MultiImageLoader,
    "LTXSequencer": LTXSequencer,
    "SpeechLengthCalculator": SpeechLengthCalculator,
    "LoadAudioUI": LoadAudioUI,
    "LoadVideoUI": LoadVideoUI,
    "LTXDirector": LTXDirector,
    "LTXDirectorGuide": LTXDirectorGuide,
    "LTXDirectorCropGuides": LTXDirectorCropGuides,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LTXKeyframer": "LTX Keyframer",
    "MultiImageLoader": "Multi Image Loader",
    "LTXSequencer": "LTX Sequencer",
    "SpeechLengthCalculator": "Speech Length Calculator",
    "LoadAudioUI": "Load Audio UI",
    "LoadVideoUI": "Load Video UI",
    "LTXDirector": "LTX Director",
    "LTXDirectorGuide": "LTX Director Guide",
    "LTXDirectorCropGuides": "LTX Director Crop Guides",
}

WEB_DIRECTORY = "./js"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']