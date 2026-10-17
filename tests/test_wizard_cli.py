import argparse

from ninerouter_omni import setup_cmd


def _parse(argv):
    parser = argparse.ArgumentParser(prog="hermes")
    subs = parser.add_subparsers(dest="command")
    p9 = subs.add_parser("9router")
    setup_cmd.register_subcommand(p9)
    return parser.parse_args(argv)


def test_subcommand_registers_setup_with_flags():
    ns = _parse(["9router", "setup", "--yes", "--tts-model", "openai/tts-1", "--voice", "nova"])
    assert ns.nine_router_command == "setup"
    assert ns.yes is True and ns.tts_model == "openai/tts-1" and ns.voice == "nova"
    assert ns.func is setup_cmd.handle_setup


def test_subcommand_defaults():
    ns = _parse(["9router", "setup"])
    assert ns.yes is False and ns.tts_model is None and ns.voice is None
