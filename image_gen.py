"""9router image generation provider for Hermes.

Implements :class:`agent.image_gen_provider.ImageGenProvider`. Routes
``image_generate`` tool calls to ``POST /v1/images/generations`` on the
configured 9router gateway. Activate via ``image_gen.provider: "9router"`` in
``~/.hermes/config.yaml``.

Optional config under ``image_gen.9router``:

.. code-block:: yaml

    image_gen:
      provider: 9router
      9router:
        model: "gemini/gemini-3-pro-image-preview"   # default
        quality: "high"                              # optional, passed through
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_b64_image,
    success_response,
)

from ._http import is_configured, post_json

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini/gemini-3-pro-image-preview"

_SIZES = {
    "landscape": "1536x1024",
    "square": "1024x1024",
    "portrait": "1024x1536",
}


def _load_9router_image_config() -> Dict[str, Any]:
    """Read ``image_gen.9router`` from config.yaml (empty dict on any failure)."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        if not isinstance(section, dict):
            return {}
        sub = section.get("9router")
        return sub if isinstance(sub, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not load image_gen.9router config: %s", exc)
        return {}


def _resolve_model() -> str:
    cfg = _load_9router_image_config()
    model = cfg.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return DEFAULT_MODEL


def _safe_prefix(model: str) -> str:
    return "9router_" + "".join(
        c if c.isalnum() or c in "-_" else "_" for c in model
    )


def _detect_image_extension(b64_data: str) -> str:
    """Sniff the first few bytes of a base64 image and return the right extension.

    9router proxies many backends; FLUX returns JPEG bytes even when we ask for
    ``b64_json``. We don't want to write a JPEG to a ``.png`` file.
    """
    try:
        head = base64.b64decode(b64_data[:32], validate=False)[:12]
    except Exception:
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"GIF8"):
        return "gif"
    if head.startswith(b"RIFF") and b"WEBP" in head:
        return "webp"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return "png"


class NineRouterImageGenProvider(ImageGenProvider):
    """9router-backed image generation provider."""

    @property
    def name(self) -> str:
        return "9router"

    @property
    def display_name(self) -> str:
        return "9router"

    def is_available(self) -> bool:
        return is_configured()

    def list_models(self) -> List[Dict[str, Any]]:
        # 9router proxies many backends — we expose a representative default
        # plus whatever the user has pinned in config. The full catalog is
        # discoverable via GET /v1/models/image on the gateway itself.
        models = [
            {
                "id": DEFAULT_MODEL,
                "display": "Gemini 3 Pro Image (default)",
                "strengths": "9router default; broad model coverage",
            }
        ]
        configured = _resolve_model()
        if configured != DEFAULT_MODEL:
            models.insert(
                0,
                {
                    "id": configured,
                    "display": f"{configured} (configured)",
                    "strengths": "Active model from image_gen.9router.model",
                },
            )
        return models

    def default_model(self) -> Optional[str]:
        return _resolve_model()

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        aspect = resolve_aspect_ratio(aspect_ratio)
        prompt_clean = (prompt or "").strip()
        if not prompt_clean:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider="9router",
                aspect_ratio=aspect,
            )

        if not is_configured():
            return error_response(
                error=(
                    "9router not configured. Set NINEROUTER_BASE_URL and "
                    "NINEROUTER_API_KEY in ~/.hermes/.env."
                ),
                error_type="auth_required",
                provider="9router",
                aspect_ratio=aspect,
            )

        cfg = _load_9router_image_config()
        model = _resolve_model()
        size = _SIZES[aspect]
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt_clean,
            "size": size,
            "n": 1,
            "response_format": "b64_json",
        }
        quality = cfg.get("quality")
        if isinstance(quality, str) and quality.strip():
            payload["quality"] = quality.strip()

        logger.info("9router image: model=%s size=%s prompt=%r", model, size, prompt_clean[:80])

        try:
            response = post_json("/v1/images/generations", payload, timeout=180)
        except ValueError as exc:  # missing env
            return error_response(
                error=str(exc),
                error_type="auth_required",
                provider="9router",
                model=model,
                prompt=prompt_clean,
                aspect_ratio=aspect,
            )
        except Exception as exc:  # noqa: BLE001 — incl. httpx + RuntimeError
            logger.warning("9router image generation failed: %s", exc)
            return error_response(
                error=f"9router image generation failed: {exc}",
                error_type="api_error",
                provider="9router",
                model=model,
                prompt=prompt_clean,
                aspect_ratio=aspect,
            )

        items = response.get("data") if isinstance(response, dict) else None
        if not isinstance(items, list) or not items:
            return error_response(
                error="9router response contained no image data",
                error_type="empty_response",
                provider="9router",
                model=model,
                prompt=prompt_clean,
                aspect_ratio=aspect,
            )

        first = items[0] if isinstance(items[0], dict) else {}
        b64 = first.get("b64_json")
        url = first.get("url")

        # Prefer b64_json (we asked for it) and save locally. If the gateway
        # ignored response_format and returned a URL, hand that back as-is.
        if isinstance(b64, str) and b64:
            try:
                saved_path = save_b64_image(
                    b64,
                    prefix=_safe_prefix(model),
                    extension=_detect_image_extension(b64),
                )
            except Exception as exc:  # noqa: BLE001
                return error_response(
                    error=f"Could not save 9router image to cache: {exc}",
                    error_type="io_error",
                    provider="9router",
                    model=model,
                    prompt=prompt_clean,
                    aspect_ratio=aspect,
                )
            image_ref = str(saved_path)
        elif isinstance(url, str) and url:
            image_ref = url
        else:
            return error_response(
                error="9router response missing both b64_json and url",
                error_type="empty_response",
                provider="9router",
                model=model,
                prompt=prompt_clean,
                aspect_ratio=aspect,
            )

        extra: Dict[str, Any] = {"size": size}
        if "revised_prompt" in first:
            extra["revised_prompt"] = first["revised_prompt"]

        return success_response(
            image=image_ref,
            model=model,
            prompt=prompt_clean,
            aspect_ratio=aspect,
            provider="9router",
            extra=extra,
        )

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "9router",
            "badge": "self-hosted",
            "tag": "Self-hosted 9router gateway — proxies /v1/images/generations.",
            "env_vars": [
                {
                    "key": "NINEROUTER_BASE_URL",
                    "prompt": "9router gateway base URL (e.g. http://127.0.0.1:20128)",
                    "url": "",
                },
                {
                    "key": "NINEROUTER_API_KEY",
                    "prompt": "9router API key",
                    "url": "",
                },
            ],
        }
