from __future__ import annotations

import json

from getpass import getpass
from pathlib import Path

from werkzeug.security import (
    generate_password_hash,
)


PASSWORD_FILE = (
    Path(__file__).resolve().parent
    / "passwords.json"
)


def main():
    password = getpass(
        "New Receipt Control password: "
    )

    confirmation = getpass(
        "Confirm password: "
    )

    if password != confirmation:
        raise SystemExit(
            "Passwords do not match."
        )

    if len(password) < 10:
        raise SystemExit(
            "Use at least 10 characters."
        )

    password_hash = (
        generate_password_hash(
            password
        )
    )

    PASSWORD_FILE.write_text(
        json.dumps(
            {
                "password_hash":
                    password_hash
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\nPassword hash saved to:"
    )

    print(PASSWORD_FILE)


if __name__ == "__main__":
    main()