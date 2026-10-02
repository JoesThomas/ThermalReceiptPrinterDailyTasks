"""Archive reprints run under the same bounded supervisor as live printing."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from receipt.archive import reprint

if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Invalid archive command')
    reprint(sys.argv[1], sys.argv[2])
