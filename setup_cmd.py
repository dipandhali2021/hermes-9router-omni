"""``hermes 9router setup`` — live-catalog model wizard.

Pure planner at module level (no Hermes imports); the interactive wizard and
the CLI subcommand live further down this module and import Hermes lazily
inside functions.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .catalog import (
    CatalogEntry,
    fetch_catalog,
    group_by_provider,
    probe_auth,
    split_web,
)
from .settings import (
    PROVIDER_NAME,
    TTS_VOICE_SUGGESTIONS,
    resolve_fetch_model,
    resolve_image_model,
    resolve_search_model,
    resolve_stt_model,
    resolve_tts_model,
)

CAPABILITY_LABELS: Dict[str, str] = {
    "web_search": "Web search",
    "web_fetch": "Web fetch",
    "tts": "Text-to-speech",
    "stt": "Speech-to-text",
    "image": "Image generation",
}

_CAPABILITY_SOURCES = {
    "web_search": "web",
    "web_fetch": "web",
    "tts": "tts",
    "stt": "stt",
    "image": "image",
}


def _clean(value: Any) -> Optional[str]:
    """Stripped non-empty string, else None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_9router(value: Any) -> bool:
    return _clean(value) == PROVIDER_NAME


def _section(cfg: Any, name: str) -> Dict[str, Any]:
    node = cfg.get(name) if isinstance(cfg, dict) else None
    return node if isinstance(node, dict) else {}


def _ensure_section(out: Dict[str, Any], name: str) -> Dict[str, Any]:
    node = out.get(name)
    if not isinstance(node, dict):
        node = {}
        out[name] = node
    return node


def _ensure_sub(node: Dict[str, Any], key: str) -> Dict[str, Any]:
    sub = node.get(key)
    if not isinstance(sub, dict):
        sub = {}
        node[key] = sub
    return sub


def current_picks(cfg: Any) -> Dict[str, bool]:
    """Which capabilities currently route through 9router (§6.2 semantics).

    Web: a set ``search_backend`` / ``extract_backend`` wins over the shared
    ``web.backend`` fallback.
    """
    web = _section(cfg, "web")
    backend = web.get("backend")
    search = _clean(web.get("search_backend")) or backend
    fetch = _clean(web.get("extract_backend")) or backend

    return {
        "web_search": _is_9router(search),
        "web_fetch": _is_9router(fetch),
        "tts": _is_9router(_section(cfg, "tts").get("provider")),
        "stt": _is_9router(_section(cfg, "stt").get("provider")),
        "image": _is_9router(_section(cfg, "image_gen").get("provider")),
    }


def default_selection(cfg: Any) -> Dict[str, bool]:
    """Checklist defaults: mirror the existing config, or all-on on first run."""
    picks = current_picks(cfg)
    if any(picks.values()):
        return picks
    return {capability: True for capability in CAPABILITY_LABELS}


def plan_writes(
    cfg: Any,
    decisions: Mapping[str, Optional[bool]],
    *,
    models: Mapping[str, Optional[str]],
    voice: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the new config dict for the wizard's decisions.

    ``True`` enables + writes the model; ``False`` disables 9router-owned
    values only (model keys stay, foreign providers stay, ``web.backend`` is
    deleted only when *both* web capabilities are turned off); ``None``
    leaves the capability untouched. Never mutates ``cfg``.
    """
    out = copy.deepcopy(cfg) if isinstance(cfg, dict) else {}

    def enabled(capability: str) -> bool:
        return decisions.get(capability) is True

    def disabled(capability: str) -> bool:
        return decisions.get(capability) is False

    # ---- enables ----------------------------------------------------------
    if enabled("web_search"):
        web = _ensure_section(out, "web")
        web["search_backend"] = PROVIDER_NAME
        search_model = _clean(models.get("web_search"))
        if search_model:
            _ensure_sub(web, "9router")["search_model"] = search_model

    if enabled("web_fetch"):
        web = _ensure_section(out, "web")
        web["extract_backend"] = PROVIDER_NAME
        fetch_model = _clean(models.get("web_fetch"))
        if fetch_model:
            _ensure_sub(web, "9router")["fetch_model"] = fetch_model

    if enabled("tts"):
        tts = _ensure_section(out, "tts")
        tts["provider"] = PROVIDER_NAME
        tts_model = _clean(models.get("tts"))
        if tts_model:
            tts["model"] = tts_model
        tts_voice = _clean(voice)
        # Combo models take no voice suffix (§6.3): never persist the pair,
        # even when a caller passes one in explicitly.
        if tts_voice and not (tts_model or "").endswith("-combo"):
            tts["voice"] = tts_voice

    if enabled("stt"):
        stt = _ensure_section(out, "stt")
        stt["provider"] = PROVIDER_NAME
        stt["enabled"] = True
        stt_model = _clean(models.get("stt"))
        if stt_model:
            _ensure_sub(stt, "9router")["model"] = stt_model

    if enabled("image"):
        image = _ensure_section(out, "image_gen")
        image["provider"] = PROVIDER_NAME
        image_model = _clean(models.get("image"))
        if image_model:
            image["model"] = image_model

    # ---- disables (9router-owned values only; model keys stay) ------------
    if disabled("web_search"):
        web = out.get("web")
        if isinstance(web, dict) and _is_9router(web.get("search_backend")):
            del web["search_backend"]

    if disabled("web_fetch"):
        web = out.get("web")
        if isinstance(web, dict) and _is_9router(web.get("extract_backend")):
            del web["extract_backend"]

    if disabled("web_search") and disabled("web_fetch"):
        web = out.get("web")
        if isinstance(web, dict) and _is_9router(web.get("backend")):
            del web["backend"]

    if disabled("tts"):
        tts = out.get("tts")
        if isinstance(tts, dict) and _is_9router(tts.get("provider")):
            del tts["provider"]

    if disabled("stt"):
        stt = out.get("stt")
        if isinstance(stt, dict) and _is_9router(stt.get("provider")):
            del stt["provider"]

    if disabled("image"):
        image = out.get("image_gen")
        if isinstance(image, dict) and _is_9router(image.get("provider")):
            del image["provider"]

    return out


def fetch_capability_models(capability: str) -> List[CatalogEntry]:
    """Live catalog for one wizard capability (web gets split by kind)."""
    entries = fetch_catalog(_CAPABILITY_SOURCES[capability])
    if capability in ("web_search", "web_fetch"):
        search, fetch = split_web(entries)
        return search if capability == "web_search" else fetch
    return entries


def build_scripted_plan(
    cfg: Any, args: Any
) -> Tuple[Dict[str, bool], Dict[str, str], Optional[str]]:
    """The ``--yes`` path: enable everything, flags > current config > defaults."""
    decisions = {capability: True for capability in CAPABILITY_LABELS}
    models = {
        "web_search": getattr(args, "search_model", None) or resolve_search_model(cfg),
        "web_fetch": getattr(args, "fetch_model", None) or resolve_fetch_model(cfg),
        "tts": getattr(args, "tts_model", None) or resolve_tts_model(cfg),
        "stt": getattr(args, "stt_model", None) or resolve_stt_model(cfg),
        "image": getattr(args, "image_model", None) or resolve_image_model(cfg),
    }
    voice = _clean(getattr(args, "voice", None))
    return decisions, models, voice


# ---------------------------------------------------------------------------
# Interactive wizard + CLI subcommand
# ---------------------------------------------------------------------------


def register_subcommand(parser: Any) -> None:
    """``hermes 9router setup`` — registered as the plugin's CLI setup_fn."""
    sub = parser.add_subparsers(dest="nine_router_command")
    sp = sub.add_parser(
        "setup",
        help="Pick 9router models from your gateway's live catalog",
    )
    sp.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Non-interactive: mirror the existing config, fill the rest "
            "with defaults, enable all five capabilities"
        ),
    )
    sp.add_argument("--tts-model", default=None, help="TTS model id (e.g. openai/tts-1)")
    sp.add_argument("--stt-model", default=None, help="STT model id (e.g. groq/whisper-large-v3-turbo)")
    sp.add_argument("--image-model", default=None, help="Image model id (e.g. image-combo)")
    sp.add_argument("--search-model", default=None, help="Web search model id (e.g. tavily/search)")
    sp.add_argument("--fetch-model", default=None, help="Web fetch model id (e.g. exa/fetch)")
    sp.add_argument("--voice", default=None, help="TTS voice (free text, e.g. nova)")
    sp.set_defaults(func=handle_setup)


def handle_setup(args: Any) -> int:
    """CLI handler (handler_fn). Routes ``hermes 9router setup`` to the wizard.

    Hermes discards a handler's return value, so a failing wizard run exits
    the process non-zero for scripted installs (§6.1 step 7).
    """
    if getattr(args, "nine_router_command", None) != "setup":
        print("Run `hermes 9router setup` to configure models.")
        return 1
    rc = run_wizard(args)
    if rc:
        raise SystemExit(rc)
    return rc


def run_wizard(args: Any) -> int:
    """The §6.1 install-and-configure flow.

    Hermes and rich imports stay inside this function so the planner half of
    the module (and its tests) run without Hermes installed.
    """
    import os
    import sys

    from rich.console import Console
    from rich.prompt import Confirm

    from hermes_cli.config import (
        get_env_value,
        load_config,
        save_config,
        save_env_value,
    )
    from hermes_cli.curses_ui import curses_checklist, curses_single_select
    from hermes_cli.secret_prompt import masked_secret_prompt

    console = Console()
    yes = bool(getattr(args, "yes", False))
    if not yes and not sys.stdin.isatty():
        console.print(
            "Refusing to run interactively without a TTY — "
            "use `--yes` for scripted installs."
        )
        return 1

    cfg = load_config()

    if yes:
        # -------- scripted path: flags > current config > defaults ---------
        base = (get_env_value("NINEROUTER_BASE_URL") or "").strip()
        if not base:
            console.print(
                "Set NINEROUTER_BASE_URL first "
                "(e.g. NINEROUTER_BASE_URL=http://127.0.0.1:20128)."
            )
            return 1
        key = (get_env_value("NINEROUTER_API_KEY") or "").strip()
        os.environ["NINEROUTER_BASE_URL"] = base
        if key:
            os.environ["NINEROUTER_API_KEY"] = key
        decisions, models, voice = build_scripted_plan(cfg, args)
        combo_picked: Dict[str, bool] = {}
    else:
        # -------- env check (§6.1 step 1) ----------------------------------
        base = (get_env_value("NINEROUTER_BASE_URL") or "").strip()
        if not base:
            base = input(
                "9router gateway base URL (e.g. http://127.0.0.1:20128): "
            ).strip()
            if not base:
                console.print("[red]A gateway base URL is required.[/red]")
                return 1

        require_key = Confirm.ask("Does your gateway require an API key?", default=True)
        existing_key = (get_env_value("NINEROUTER_API_KEY") or "").strip()
        if require_key:
            key = existing_key
            if not key:
                key = masked_secret_prompt("NINEROUTER_API_KEY: ").strip()
        else:
            key = ""
            if existing_key:
                save_env_value("NINEROUTER_API_KEY", "")
                console.print("Stored API key cleared — running keyless.")

        save_env_value("NINEROUTER_BASE_URL", base)
        if require_key:
            save_env_value("NINEROUTER_API_KEY", key)
        os.environ["NINEROUTER_BASE_URL"] = base
        if key:
            os.environ["NINEROUTER_API_KEY"] = key
        else:
            os.environ.pop("NINEROUTER_API_KEY", None)

        def reprompt_endpoint(cur_base: str, cur_key: str) -> Tuple[str, str]:
            """Re-prompt base URL (+ key when required) and persist both."""
            new_base = input(f"Gateway base URL [{cur_base}]: ").strip() or cur_base
            save_env_value("NINEROUTER_BASE_URL", new_base)
            os.environ["NINEROUTER_BASE_URL"] = new_base
            new_key = cur_key
            if require_key:
                entered = masked_secret_prompt(
                    "NINEROUTER_API_KEY (Enter to keep current): "
                ).strip()
                new_key = entered or cur_key
                save_env_value("NINEROUTER_API_KEY", new_key)
                if new_key:
                    os.environ["NINEROUTER_API_KEY"] = new_key
                else:
                    os.environ.pop("NINEROUTER_API_KEY", None)
            return new_base, new_key

        # -------- connect + auth probe (§6.1 step 2, max 3 attempts) -------
        for _attempt in range(3):
            try:
                fetch_catalog("tts")
            except Exception as exc:
                console.print(
                    f"[red]Could not reach the gateway at {base}:[/red] {exc}"
                )
                base, key = reprompt_endpoint(base, key)
                continue

            probe = probe_auth(base, key)
            if probe.ok:
                break
            if probe.status in (401, 403):
                console.print("[red]API key rejected.[/red]")
                key = masked_secret_prompt("NINEROUTER_API_KEY: ").strip()
                save_env_value("NINEROUTER_API_KEY", key)
                if key:
                    os.environ["NINEROUTER_API_KEY"] = key
                else:
                    os.environ.pop("NINEROUTER_API_KEY", None)
            else:
                console.print(f"[red]Auth probe failed:[/red] {probe.detail}")
                base, key = reprompt_endpoint(base, key)
        else:
            console.print(
                "[red]Could not verify the gateway after 3 attempts. Check that "
                "9router is running, the base URL is right, and (when required) "
                "NINEROUTER_API_KEY is valid — then re-run "
                "`hermes 9router setup`. No config was written.[/red]"
            )
            return 1

        # -------- capability checklist (§6.1 step 3) -----------------------
        defaults = default_selection(cfg)
        selected = {
            i for i, cap in enumerate(CAPABILITY_LABELS) if defaults[cap]
        }
        chosen = curses_checklist(
            "Route which capabilities through 9router?",
            list(CAPABILITY_LABELS.values()),
            selected,
            cancel_returns=selected,
        )
        decisions = {
            cap: (i in chosen) for i, cap in enumerate(CAPABILITY_LABELS)
        }

        # -------- per-capability model picks (§6.1 step 4) -----------------
        models: Dict[str, str] = {}
        combo_picked: Dict[str, bool] = {}
        flag_models = {
            "web_search": getattr(args, "search_model", None),
            "web_fetch": getattr(args, "fetch_model", None),
            "tts": getattr(args, "tts_model", None),
            "stt": getattr(args, "stt_model", None),
            "image": getattr(args, "image_model", None),
        }
        resolvers = {
            "web_search": resolve_search_model,
            "web_fetch": resolve_fetch_model,
            "tts": resolve_tts_model,
            "stt": resolve_stt_model,
            "image": resolve_image_model,
        }

        for cap, label in CAPABILITY_LABELS.items():
            if decisions.get(cap) is not True:
                continue

            entries: Optional[List[CatalogEntry]] = None
            while entries is None:
                try:
                    entries = fetch_capability_models(cap)
                except Exception as exc:
                    console.print(
                        f"[red]Could not fetch the {label} catalog:[/red] {exc}"
                    )
                    if not Confirm.ask("Retry?", default=True):
                        decisions[cap] = None
                        break
            if entries is None:
                continue
            if not entries:
                console.print(
                    f"[yellow]The {label} catalog is empty — "
                    "leaving it untouched.[/yellow]"
                )
                decisions[cap] = None
                continue

            flag = flag_models.get(cap)
            if flag:
                match = next((e for e in entries if e.id == flag), None)
                models[cap] = flag
                combo_picked[cap] = (
                    match.is_combo if match is not None else flag.endswith("-combo")
                )
                console.print(f"[green]{label}:[/green] {flag} (flag)")
                continue

            current = resolvers[cap](cfg)
            groups = group_by_provider(entries)
            group_keys = list(groups)
            group_labels = [
                "Combos (auto-fallback)" if key == "combo" else key
                for key in group_keys
            ]

            picked = False
            while not picked:
                group_index = curses_single_select(
                    f"{label} — provider group",
                    group_labels,
                    searchable=True,
                )
                if group_index is None:
                    decisions[cap] = None  # ESC: leave the capability untouched
                    break

                group_entries = groups[group_keys[group_index]]
                item_labels = [
                    entry.id + ("  (currently in use)" if entry.id == current else "")
                    for entry in group_entries
                ]
                default_index = next(
                    (i for i, e in enumerate(group_entries) if e.id == current), 0
                )
                model_index = curses_single_select(
                    f"{label} — model",
                    item_labels,
                    default_index=default_index,
                    searchable=True,
                )
                if model_index is None:
                    continue  # ESC: back to the provider group step

                entry = group_entries[model_index]
                models[cap] = entry.id
                combo_picked[cap] = entry.is_combo
                picked = True

        # -------- TTS voice (§6.1 step 5; combos reject voice suffixes) ----
        voice = _clean(getattr(args, "voice", None))
        if (
            decisions.get("tts") is True
            and voice is None
            and not combo_picked.get("tts", False)
        ):
            console.print(
                "Voice suggestions: " + ", ".join(TTS_VOICE_SUGGESTIONS)
            )
            answer = input(
                "TTS voice (empty = leave tts.voice unchanged): "
            ).strip()
            voice = answer or None

    # A combo model accepts no voice suffix (§6.3): warn about it, and never
    # persist the pair — the write planner enforces the same rule.
    if (
        voice
        and decisions.get("tts") is True
        and (
            combo_picked.get("tts", False)
            or str(models.get("tts") or "").endswith("-combo")
        )
    ):
        console.print(
            "[yellow]Voice ignored: combo models take no voice suffix.[/yellow]"
        )
        voice = None

    # -------- write config (§6.1 step 6) -----------------------------------
    out = plan_writes(cfg, decisions, models=models, voice=voice)

    console.print()
    console.print("[bold]9router setup[/bold]")
    for cap, label in CAPABILITY_LABELS.items():
        decision = decisions.get(cap)
        if decision is True:
            suffix = f" — {models.get(cap)}" if models.get(cap) else ""
            if cap == "tts" and voice:
                suffix += f" (voice: {voice})"
            console.print(f"  [green]✓[/green] {label}: enabled{suffix}")
        elif decision is False:
            console.print(
                f"  [yellow]✗[/yellow] {label}: disabled (9router routing removed)"
            )
        else:
            console.print(f"  [dim]–[/dim] {label}: left untouched")
    save_config(out)

    # -------- smoke test (§6.1 step 7) -------------------------------------
    console.print()
    console.print("[bold]Smoke test[/bold]")
    failures = 0
    for cap, label in CAPABILITY_LABELS.items():
        if decisions.get(cap) is not True:
            continue
        try:
            fetch_capability_models(cap)
            console.print(f"  [green]✓[/green] {label}")
        except Exception as exc:
            failures += 1
            console.print(f"  [red]✗[/red] {label}: {exc}")
    if failures:
        console.print(
            "[red]The smoke test failed for some capabilities. The config was "
            "saved; fix the gateway/network and re-run "
            "`hermes 9router setup`.[/red]"
        )
        return 1

    console.print()
    console.print("restart the gateway: hermes gateway restart")
    return 0
