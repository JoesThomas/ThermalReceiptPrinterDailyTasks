"""Bounded ESC/POS sensor queries; unsupported or ambiguous responses stay unknown.

Protocol: https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/dle_eot.html
Only an explicit diagnostic sends status commands; no feed, cut or print command.
"""

import os
from pathlib import Path
import socket
from storage import file_lock
from receipt.printer import DEFAULT_NETWORK_HOST, DEFAULT_NETWORK_PORT

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = {
    "cover": "unknown",
    "paper": "unknown",
    "paper_low": "unknown",
    "error": "unknown",
}


def decode(offline, paper):
    result = dict(UNKNOWN)

    def valid(value):
        return isinstance(value, bytes) and len(value) == 1 and value[0] & 0x93 == 0x12

    if not valid(offline):
        return result
    result["cover"] = "open" if offline[0] & 0x04 else "closed"
    result["error"] = "reported" if offline[0] & 0x40 else "not reported"
    # With an open cover, the paper bits can retain a previous reading.
    if result["cover"] == "open" or not valid(paper):
        return result
    end, low = paper[0] & 0x60, paper[0] & 0x0C
    if end in (0, 0x60):
        result["paper"] = "out" if end else "present"
    if low in (0, 0x0C):
        result["paper_low"] = "reported" if low else "not reported"
    return result


def busy(root):
    for name in (".print_now.lock", ".live_preview.lock"):
        try:
            pid = int((Path(root) / "data" / name).read_text())
            if not 0 < pid <= 2147483647:
                continue
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except (OSError, ValueError):
            pass
    return False


def sensors(root=ROOT):
    result = dict(
        UNKNOWN,
        message="Sensor status unavailable; this printer may not support status replies.",
    )
    if os.getenv("RECEIPT_PRINTER_CONNECTION", "network").strip().lower() != "network":
        result["message"] = (
            "Sensor queries currently support network printers; USB sensor status is unknown."
        )
        return result
    try:
        with file_lock(Path(root) / "data" / "printer_diagnostic_run", blocking=False):
            if busy(root):
                result["message"] = "Receipt job active; sensor check deferred."
                return result
            host = os.getenv("RECEIPT_PRINTER_HOST", DEFAULT_NETWORK_HOST).strip()
            port = int(os.getenv("RECEIPT_PRINTER_PORT", str(DEFAULT_NETWORK_PORT)))
            if not host or not 1 <= port <= 65535:
                raise ValueError()
            with socket.create_connection((host, port), timeout=3) as stream:
                stream.settimeout(1)
                stream.sendall(b"\x10\x04\x02")
                offline = stream.recv(1)
                if not offline or len(offline) != 1 or offline[0] & 0x93 != 0x12:
                    return result
                stream.sendall(b"\x10\x04\x04")
                try:
                    paper = stream.recv(1)
                except OSError:
                    paper = b""
                result.update(decode(offline, paper))
                result["message"] = (
                    "Printer reported sensor status. Missing sensors and paper delivery remain unverified."
                )
    except BlockingIOError:
        result["message"] = (
            "Another printer operation is active; sensor check deferred."
        )
    except (OSError, ValueError):
        pass
    return result
