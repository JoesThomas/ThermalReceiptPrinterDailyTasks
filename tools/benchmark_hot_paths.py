"""Repeatable synthetic benchmarks; no credentials, remote APIs or printer access."""

import argparse
import hashlib
import inspect
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 100:
        parser.error("Choose 1 to 100 iterations")
    sys.path.insert(0, str(args.source_root.resolve()))
    from finance_trends import category_trends
    from finance import wealth_history
    from receipt import archive

    try:
        from receipt.text import printer_safe_text
    except ImportError:
        # Load only the historical pure helper; importing the old CLI reads private config.
        import ast
        import re
        import unicodedata

        source = ast.parse((args.source_root / "print_google_doc.py").read_text())
        node = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "printer_safe_text"
        )
        namespace = {"re": re, "unicodedata": unicodedata}
        exec(
            compile(
                ast.Module(body=[node], type_ignores=[]),
                "printer_text_benchmark",
                "exec",
            ),
            namespace,
        )
        printer_safe_text = namespace["printer_safe_text"]
    try:
        from services.parallel import collect_independent
    except ImportError:
        collect_independent = None
    today = date(2026, 10, 11)
    records = [
        {
            "date": (today - timedelta(days=index % 120)).isoformat(),
            "description": f"SHOP {index % 60}",
            "amount": -(index % 100 + 1),
        }
        for index in range(10000)
    ]
    rules = {f"SHOP {index}": "SHOPPING" for index in range(60)}
    rules["transactions"] = [
        {
            "date": (today - timedelta(days=index)).isoformat(),
            "merchant": "SHOP",
            "amount": 200,
            "category": "PRESENT",
        }
        for index in range(100)
    ]
    valuations = [
        {
            "id": f"{account}-{index}",
            "kind": "savings",
            "name": f"Account {account:03}",
            "date": (today - timedelta(days=49 - index)).isoformat(),
            "balance": str(100 + index * 10),
            "deposits": "10",
            "withdrawals": "0",
        }
        for account in range(200)
        for index in range(50)
    ]
    output = {}

    def measure(name, calculate):
        start = time.perf_counter()
        for _ in range(args.iterations):
            value = calculate()
        output[name] = {
            "milliseconds": round(
                (time.perf_counter() - start) * 1000 / args.iterations, 2
            ),
            "result_hash": hashlib.sha256(
                json.dumps(value, sort_keys=True, default=str).encode()
            ).hexdigest()[:16],
        }

    measure(
        "transaction_trends_10000", lambda: category_trends(records, rules, as_of=today)
    )
    with patch.object(wealth_history, "load_history", return_value=valuations):
        measure("wealth_history_200_accounts", lambda: wealth_history.review(today))
    measure(
        "printer_text_10000_lines",
        lambda: [
            printer_safe_text(f"RECEIPT ITEM {index}: 25.00") for index in range(10000)
        ],
    )
    with (
        TemporaryDirectory() as directory,
        patch.object(archive, "DIRECTORY", Path(directory)),
    ):
        for index in range(300):
            identifier = f"20261011T120000Z-{index:012x}"
            value = {
                "id": identifier,
                "captured_at": (
                    datetime(2026, 10, 11, tzinfo=timezone.utc)
                    + timedelta(minutes=index)
                ).isoformat(),
                "source": "preview",
                "pages": {"information": f"Item {index}"},
                "page_images": {
                    "information": ["data:image/png;base64," + "A" * 100000]
                },
                "freshness": {},
            }
            (Path(directory) / (identifier + ".json")).write_text(json.dumps(value))
        if hasattr(archive, "_entry_summary"):
            archive._entry_summary.cache_clear()
        listing = (
            (lambda: archive.entries(limit=50))
            if "limit" in inspect.signature(archive.entries).parameters
            else (lambda: archive.entries()[:50])
        )
        measure("archive_300_receipts_first_page", listing)
        measure("archive_300_receipts_repeat_page", listing)
    tasks = {
        str(index): (lambda index=index: (time.sleep(0.02), index)[1])
        for index in range(4)
    }
    if collect_independent:
        measure(
            "independent_sources_4x20ms",
            lambda: {
                name: future.result()
                for name, future in collect_independent(tasks).items()
            },
        )
    else:
        measure(
            "independent_sources_4x20ms",
            lambda: {name: task() for name, task in tasks.items()},
        )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
