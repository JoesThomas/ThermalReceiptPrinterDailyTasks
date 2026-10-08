# Raspberry Pi deployment

Use a 64-bit Raspberry Pi OS installation and Python 3.11 or newer. This repository's automated checks use simulated integrations and do not prove physical Pi/printer behaviour.

1. Create a dedicated `receipt` user and clone the repository at `/opt/thermal-receipt`, owned by that user.
2. Create `/opt/thermal-receipt/.venv` with `python3 -m venv .venv`; install `requirements.txt` and `web_control/requirements.txt` using its pip.
3. Copy your private configuration and local data using the backup/restore interface. Do not commit credentials. Give the service user ownership and keep files private.
4. Copy `thermal-receipt.env.example` to `/etc/thermal-receipt.env`, review the printer address and web binding, and set owner-only permissions. The loopback default needs an SSH tunnel for access from another machine. If you change the binding, configure authentication before exposing it.
5. Copy `receipt-control.service` to `/etc/systemd/system/receipt-control.service`. Run `sudo systemctl daemon-reload` then `sudo systemctl enable --now receipt-control`.
6. Check `sudo systemctl status receipt-control` and `sudo journalctl -u receipt-control -n 60`. Run `/opt/thermal-receipt/.venv/bin/python main.py --health` from the project directory and review **Prepare print → Installation checks**.

Use only the application's scheduler; disable any older cron/launchd printing jobs to avoid duplicate receipts. A systemd service restart does not independently trigger a print.

## Physical acceptance checks

- Reboot the Pi: confirm the authenticated interface returns and the next scheduled print time is correct in UK time.
- Generate a live preview without printing; compare the pages with the physical output.
- Disconnect the printer, request a print, and confirm the generated preview remains available. Reconnect and explicitly print the saved copy; no automatic duplicate print should occur.
- Disconnect the Pi's network and check the displayed ages of cached source data. Restore the network and retry the affected source.
- Temporarily set a near-term print time, confirm only one scheduled receipt is sent, then restore your preferred time.
- Stop the service during a job: confirm its worker stops too and restart does not leave a stale lock. Use job controls to cancel a long job.

The service template restarts a failed web process and stops its process group on shutdown. It does not acknowledge paper delivery, retry a partially printed receipt, or claim that external APIs are healthy.
