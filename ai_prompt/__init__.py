"""
ai_prompt -- the LTX Director's built-in prompt generator (local Ollama, self-contained).

One button in the Director UI sends the node's own timeline_data to a local Ollama vision
model, which writes the GLOBAL prompt + one SEGMENT prompt per timeline beat under the
vendored LTX prompting rules (see skills/ and prompt_builder.py), and the results land
back in the Director's prompt boxes.

Self-contained by design: stdlib-only HTTP (no ollama pip package), skills vendored as
plain .md files, no imports from any outside project. Deleting this folder (and the
routes hook in the pack __init__) removes the feature completely.

Import here stays light -- the heavy pieces load on first use.
"""
