## 9router-omni installed

First enable automatically routes web search, web extract, TTS, STT, and
image generation through 9router using sensible defaults.

STT also handles audio files dropped into the interactive TUI: the plugin
transcribes them through 9router before the model sees the turn. Restart the
TUI after install/update so the attachment hook loads.

To choose different models or a voice, run:

    hermes 9router setup

The wizard is re-runnable any time; it also lets you disable a capability.
Your later changes are not overwritten by the first-install defaults.

Keyless gateways are supported — leave `NINEROUTER_API_KEY` empty.
