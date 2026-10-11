"""Measure fresh-process imports and peak memory on this machine, without API calls."""

import argparse
import contextlib
import importlib
import io
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-web",
        action="store_true",
        help="Also import the configured web app; requires its local secret key",
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        sys.path.insert(0, str(ROOT))
        start = perf_counter()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                importlib.import_module(args.worker)
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            print(
                json.dumps(
                    {
                        "import_seconds": round(perf_counter() - start, 4),
                        "peak_rss_mib": round(
                            peak / (1024 * 1024 if sys.platform == "darwin" else 1024),
                            2,
                        ),
                    }
                )
            )
        except Exception as error:
            print(json.dumps({"error_type": type(error).__name__}))
        return
    if not 1 <= args.iterations <= 20:
        parser.error("Choose 1 to 20 iterations")
    modules = ["receipt.text", "finance.scenario_plan", "services.bank_transport"]
    if args.include_web:
        modules.append("web_control.app")
    output = {
        "python": platform.python_version(),
        "system": platform.system(),
        "architecture": platform.machine(),
        "iterations": args.iterations,
        "modules": {},
    }
    for module in modules:
        rows = []
        for _ in range(args.iterations):
            start = perf_counter()
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", module],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            row = json.loads(result.stdout)
            row["process_seconds"] = round(perf_counter() - start, 4)
            rows.append(row)
        output["modules"][module] = rows
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
