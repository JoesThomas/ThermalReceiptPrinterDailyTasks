"""Run Receipt Control with a configurable bind address and clear errors."""
from __future__ import annotations

import errno
import os


def server_address(environ=None):
    environ = os.environ if environ is None else environ
    host = environ.get("RECEIPT_WEB_HOST", "127.0.0.1").strip()
    if not host:
        raise ValueError("RECEIPT_WEB_HOST must not be empty")
    raw_port = environ.get("RECEIPT_WEB_PORT", "5050")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("RECEIPT_WEB_PORT must be a number from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("RECEIPT_WEB_PORT must be a number from 1 to 65535")
    return host, port


def bind_error_message(error, host, port):
    address = f"{host}:{port}"
    if error.errno == errno.EADDRINUSE:
        return (f"Cannot start Receipt Control on {address}: address already in use.\n"
                f"Check the listener: lsof -nP -iTCP:{port} -sTCP:LISTEN\n"
                "Stop the other server, or use RECEIPT_WEB_PORT=5051.")
    if error.errno == errno.EACCES:
        return (f"Cannot start Receipt Control on {address}: permission denied. "
                "Try another port or address you can bind.")
    if error.errno == errno.EADDRNOTAVAIL:
        return (f"Cannot start Receipt Control on {address}: address unavailable. "
                "Check RECEIPT_WEB_HOST.")
    return f"Cannot start Receipt Control on {address}: {error}"


def main(serve_fn=None, application=None, environ=None):
    real_server = serve_fn is None
    try:
        host, port = server_address(environ)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if serve_fn is None:
        from waitress import serve
        serve_fn = serve
    if application is None:
        from app import app
        application = app
    print(f"Receipt Control listening on {host}:{port}")
    try:
        # Test callers inject a server; only the real Waitress process schedules prints.
        if real_server:
            from app import _start_print_command
            from web_control.scheduled_print import start_scheduler
            start_scheduler(_start_print_command)
            from services.api_health import start_monitor
            start_monitor()
        serve_fn(application, host=host, port=port, threads=4)
    except OSError as exc:
        raise SystemExit(bind_error_message(exc, host, port)) from exc


if __name__ == "__main__":
    main()
