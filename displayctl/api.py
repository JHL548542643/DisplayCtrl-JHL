"""Loopback control API. The default bind is 127.0.0.1 and other hosts are refused."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from displayctl import __version__
from displayctl.errors import DisplayError
from displayctl.policy import (
    LUMINANCE_MAX,
    LUMINANCE_MIN,
    MAX_WRITES_PER_MINUTE,
    MIN_WRITE_INTERVAL_S,
    REQUIRED_MAXIMUM,
    VERIFY_READS,
    VERIFY_SETTLE_S,
    WRITABLE_VCP,
)
from displayctl.service import DisplayService

_ID_RE = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")
_LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "testclient"})
_DEV_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
]

_STATUS = {
    "unknown_monitor": 404,
    "value_out_of_range": 422,
    "confirm_required": 409,
    "rate_limited": 429,
    "policy_blocked": 403,
    "platform_unsupported": 503,
    "rollback_failed": 502,
    "verify_unconfirmed": 502,
    "verify_mismatch": 409,
}


class SetValueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Annotated[int, Field(ge=LUMINANCE_MIN, le=LUMINANCE_MAX, strict=True)]
    confirm: Annotated[bool, Field(strict=True)] = False


SetLuminanceBody = SetValueBody


def resolve_bind_host(host: str | None) -> str:
    value = (host or "127.0.0.1").strip().lower()
    if value in {"127.0.0.1", "localhost"}:
        return "127.0.0.1"
    if value == "::1":
        return "::1"
    raise SystemExit(f"refusing non-loopback bind: {host}")


def resolve_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or port < 1 or port > 65535:
        raise SystemExit(f"refusing port: {port}")
    return port


def build_app(service: DisplayService, *, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="DisplayCtl-JHL", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_DEV_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def loopback_only(request, call_next):
        client = request.client.host if request.client else ""
        if client not in _LOOPBACK_CLIENTS:
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "error": {
                        "kind": "policy_blocked",
                        "message": "仅接受本机连接。",
                        "retryable": False,
                    },
                },
            )
        return await call_next(request)

    @app.exception_handler(DisplayError)
    async def handle_display_error(_request, exc: DisplayError):
        return JSONResponse(
            status_code=_STATUS.get(exc.kind, 409),
            content={"ok": False, "error": exc.to_dict()},
        )

    @app.get("/api/health")
    def health():
        current: DisplayService = app.state.service
        return {
            "ok": True,
            "service": "displayctl-jhl",
            "version": __version__,
            "platform": sys.platform,
            "backend": current.backend_name,
            "demo": current.demo,
            "loopback_only": True,
            "policy": {
                "vcp": [f"0x{code:02X}" for code in WRITABLE_VCP],
                "luminance_min": LUMINANCE_MIN,
                "luminance_max": LUMINANCE_MAX,
                "required_maximum": REQUIRED_MAXIMUM,
                "min_interval_s": MIN_WRITE_INTERVAL_S,
                "max_writes_per_minute": MAX_WRITES_PER_MINUTE,
                "verify_reads": VERIFY_READS,
                "verify_settle_s": VERIFY_SETTLE_S,
            },
        }

    @app.get("/api/monitors")
    def list_monitors():
        monitors = app.state.service.enumerate_monitors()
        return {"ok": True, "monitors": [monitor.to_dict() for monitor in monitors]}

    @app.get("/api/monitors/{monitor_id}")
    def monitor_status(monitor_id: str):
        _check_id(monitor_id)
        monitor = app.state.service.probe(monitor_id)[0]
        return {"ok": True, "monitor": monitor.to_dict()}

    @app.get("/api/monitors/{monitor_id}/luminance")
    def read_luminance(monitor_id: str):
        _check_id(monitor_id)
        return {"ok": True, "luminance": app.state.service.get_luminance(monitor_id).to_dict()}

    @app.post("/api/monitors/{monitor_id}/luminance")
    def write_luminance(monitor_id: str, body: SetValueBody):
        _check_id(monitor_id)
        result = app.state.service.set_luminance_safe(monitor_id, body.value, confirm=body.confirm)
        return {"ok": True, "result": result.to_dict()}

    @app.post("/api/monitors/{monitor_id}/contrast")
    def write_contrast(monitor_id: str, body: SetValueBody):
        _check_id(monitor_id)
        result = app.state.service.set_contrast_safe(monitor_id, body.value, confirm=body.confirm)
        return {"ok": True, "result": result.to_dict()}

    @app.post("/api/monitors/{monitor_id}/volume")
    def write_volume(monitor_id: str, body: SetValueBody):
        _check_id(monitor_id)
        result = app.state.service.set_volume_safe(monitor_id, body.value, confirm=body.confirm)
        return {"ok": True, "result": result.to_dict()}

    if static_dir is not None and (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")
    return app


def _check_id(monitor_id: str) -> None:
    if not _ID_RE.fullmatch(monitor_id):
        raise DisplayError("unknown_monitor")



def create_app(*, demo: bool = False, static_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI app with demo or live backend and optional static UI."""
    if demo:
        from displayctl.demo import demo_service

        service = demo_service()
    else:
        from displayctl.service import default_service

        service = default_service()
    if static_dir is None:
        from displayctl.paths import web_dist_dir

        static_dir = web_dist_dir()
    return build_app(service, static_dir=static_dir)


def serve(host: str | None = None, port: int | None = None, *, demo: bool = False) -> None:
    import os

    import uvicorn

    from displayctl.service import default_service

    chosen_host = resolve_bind_host(host if host is not None else os.environ.get("DISPLAYCTL_HOST"))
    raw_port = 8765 if port is None else port
    if port is None and os.environ.get("DISPLAYCTL_PORT"):
        try:
            raw_port = int(os.environ["DISPLAYCTL_PORT"])
        except ValueError:
            raise SystemExit(f"refusing port: {os.environ['DISPLAYCTL_PORT']}") from None
    chosen_port = resolve_port(raw_port)
    if demo:
        from displayctl.demo import demo_service

        service = demo_service()
    else:
        service = default_service()
    from displayctl.paths import web_dist_dir
    uvicorn.run(
        build_app(service, static_dir=web_dist_dir()),
        host=chosen_host,
        port=chosen_port,
        log_level="info",
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="DisplayCtl-JHL loopback control API")
    parser.add_argument("--demo", action="store_true", help="serve memory monitors; do not open dxva2")
    parser.add_argument("--host", default=os.environ.get("DISPLAYCTL_HOST"))
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        serve(args.host, args.port, demo=args.demo)
    except ImportError:
        print("FastAPI/uvicorn is not installed. Run: pip install -e .", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
