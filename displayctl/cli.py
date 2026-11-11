"""CLI for list / get / set. ``set`` still requires ``--yes`` and then uses the safe pipeline."""

from __future__ import annotations

import argparse
import logging
import sys

from displayctl.errors import DisplayError
from displayctl.service import DisplayService, default_service


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.cmd == "api":
        return _cmd_api(args)
    if sys.platform != "win32":
        print("this tool is for Windows dxva2 only", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    service = default_service()
    try:
        return args.func(args, service)
    except DisplayError as exc:
        print(f"{exc.kind}: {exc.message}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DisplayCtl-JHL: DDC/CI luminance via Windows dxva2 VCP 0x10"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list monitors and VCP 0x10 status")
    p_list.set_defaults(func=_cmd_list)

    p_get = sub.add_parser("get", help="get luminance for one monitor")
    p_get.add_argument("index", nargs="?", type=int, default=None)
    p_get.set_defaults(func=_cmd_get)

    p_set = sub.add_parser("set", help="set luminance 0-100 (requires --yes)")
    p_set.add_argument("index", type=int)
    p_set.add_argument("value", type=int)
    p_set.add_argument("--yes", action="store_true", help="confirm the brightness write")
    p_set.set_defaults(func=_cmd_set)

    p_api = sub.add_parser("api", help="run the loopback control API")
    p_api.add_argument("--demo", action="store_true", help="memory backend, never dxva2")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)
    p_api.set_defaults(func=None)
    return parser


def _cmd_api(args: argparse.Namespace) -> int:
    try:
        from displayctl.api import serve
    except ImportError:
        print("FastAPI/uvicorn is not installed. Run: pip install -e .", file=sys.stderr)
        return 1
    serve(args.host, args.port, demo=args.demo)
    return 0


def _cmd_list(args: argparse.Namespace, service: DisplayService) -> int:
    del args
    views = service.probe()
    if not views:
        print("no physical monitors found")
        return 1
    for view in views:
        print(_format_view(view))
    failed = [view for view in views if not view.vcp_ok and not view.primary]
    if failed:
        print(
            "hint: external VCP fail is usually DDC path (OSD DDC/CI, cable/dock), "
            "not the luminance API itself"
        )
    return 0


def _cmd_get(args: argparse.Namespace, service: DisplayService) -> int:
    if args.index is None:
        return _cmd_list(args, service)
    views = service.probe()
    view = _pick(views, args.index)
    if view is None:
        return 1
    if not view.vcp_ok or view.failure or view.current is None or view.maximum is None:
        print(f"[{view.session_index}] VCP10 FAIL ({view.failure or 'probe_failed'})")
        return 2
    print(
        f"[{view.session_index}] model={view.model or '?'} "
        f"luminance={view.current}/{view.maximum} | id={view.id}"
    )
    return 0


def _cmd_set(args: argparse.Namespace, service: DisplayService) -> int:
    if not args.yes:
        print("refusing to change brightness without --yes")
        return 3
    if args.value < 0 or args.value > 100:
        print("value must be 0..100 for this tool", file=sys.stderr)
        return 1
    views = service.probe()
    view = _pick(views, args.index)
    if view is None:
        return 1
    try:
        result = service.set_luminance_safe(view.id, args.value, confirm=True)
    except DisplayError as exc:
        print(f"refusing: {exc.kind}: {exc.message}", file=sys.stderr)
        if view.failure and not view.vcp_ok:
            print(f"monitor {args.index} has no working VCP 0x10 ({exc.kind})", file=sys.stderr)
        return 5 if exc.kind in {"rollback_failed", "verify_unconfirmed"} else 4
    model = view.model or "?"
    if result.noop:
        print(
            f"[{args.index}] model={model} luminance={result.verified}/{view.maximum} "
            f"unchanged, no write | id={result.monitor_id}"
        )
        return 0
    print(
        f"[{args.index}] model={model} "
        f"{result.previous} -> set {args.value} -> read {result.verified}/{view.maximum} "
        f"| id={result.monitor_id}"
    )
    return 0


def _pick(views, index: int):
    if not views:
        print("no physical monitors found", file=sys.stderr)
        return None
    if index < 0 or index >= len(views):
        print(f"index out of range: {index} (0..{len(views) - 1})", file=sys.stderr)
        return None
    return views[index]


def _contrast_token(view) -> str:
    return _scalar_cap_token(view.capabilities.contrast, "contrast")


def _volume_token(view) -> str:
    return _scalar_cap_token(view.capabilities.volume, "volume")


def _input_token(view) -> str:
    return _scalar_cap_token(view.capabilities.input_source, "input")


def _power_token(view) -> str:
    return _scalar_cap_token(view.capabilities.power_mode, "power")


def _rgb_token(view) -> str:
    rgb = view.capabilities.rgb_gains
    if rgb is None:
        return "rgb=unknown"
    if rgb.readable:
        parts = []
        for channel in (rgb.red, rgb.green, rgb.blue):
            if channel.readable and channel.current is not None:
                parts.append(str(channel.current))
            else:
                parts.append("-")
        return "rgb=" + "/".join(parts)
    if rgb.declared:
        return "rgb=declared"
    return "rgb=absent"


def _scalar_cap_token(cap, name: str) -> str:
    if cap is None:
        return f"{name}=unknown"
    if cap.readable and cap.current is not None and cap.maximum is not None:
        return f"{name}={cap.current}/{cap.maximum}"
    if cap.declared:
        return f"{name}=declared"
    return f"{name}=absent"


def _format_view(view) -> str:
    model = view.model or "?"
    ident = f"id={view.id} stable={str(view.stable).lower()} | {_contrast_token(view)} | {_volume_token(view)} | {_rgb_token(view)} | {_input_token(view)} | {_power_token(view)}"
    if view.vcp_ok and view.failure is None:
        return (
            f"[{view.session_index}] {model} | {view.description} | {view.device} "
            f"| luminance={view.current}/{view.maximum} | primary={view.primary} | {ident}"
        )
    if view.vcp_ok:
        return (
            f"[{view.session_index}] {model} | {view.description} | {view.device} "
            f"| luminance={view.current}/{view.maximum} | REFUSE {view.failure} "
            f"| primary={view.primary} | {ident}"
        )
    winerr = "" if view.winerr is None else f" winerr={view.winerr}"
    return (
        f"[{view.session_index}] {model} | {view.description} | {view.device} "
        f"| VCP10 FAIL ({view.failure}{winerr}) | primary={view.primary} | {ident}"
    )
