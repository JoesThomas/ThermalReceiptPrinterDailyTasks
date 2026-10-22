"""Recover encrypted documents into an empty vault using its separate original key."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from organiser import vault


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    args = parser.parse_args()
    try:
        with args.backup.open('rb') as stream:
            raw = stream.read(vault.MAX_TOTAL*2+1)
        vault.restore(raw)
    except Exception:
        raise SystemExit('Restore failed. Check the original key, empty vault and encrypted backup. Existing files were not replaced.') from None
    print('Encrypted document backup restored. Expired documents were removed.')


if __name__ == '__main__':
    main()
