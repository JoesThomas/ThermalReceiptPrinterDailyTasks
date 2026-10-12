"""Compare weather/full-receipt reference images; updates require an explicit flag."""

import argparse
from pathlib import Path
import sys
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.receipt_visual_fixture import bitmap, weather_capture, full_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    directory = ROOT / "tests" / "fixtures" / "receipt_visuals"
    for name, capture in [("weather", weather_capture), ("full-receipt", full_capture)]:
        actual = bitmap(*capture())
        path = directory / (name + ".png")
        if args.update:
            directory.mkdir(parents=True, exist_ok=True)
            actual.save(path)
        else:
            expected = Image.open(path).convert("1")
            if (
                actual.size != expected.size
                or ImageChops.difference(
                    actual.convert("L"), expected.convert("L")
                ).getbbox()
            ):
                raise SystemExit(
                    f"Receipt visual changed: {name}. Review the difference before using --update."
                )
    print("Receipt visual references " + ("updated" if args.update else "passed"))


if __name__ == "__main__":
    main()
