"""Entry point for a supervised one-off note print."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from receipt.quick_note import send

if __name__ == "__main__":
    send(ROOT, sys.argv[1])
