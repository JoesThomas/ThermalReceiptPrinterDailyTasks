# Raspberry Pi deployment

Use a 64-bit Raspberry Pi OS installation and Python 3.11 or newer. This repository's automated checks use simulated integrations and do not prove physical Pi/printer behaviour.

1. Create a dedicated `receipt` user and clone the repository at `/opt/thermal-receipt`, owned by that user.
2. Create `/opt/thermal-receipt/.venv` with `python3 -m venv .venv`; install `requirements.lock` using its pip.
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

## Repeatable acceptance reports

Use `python tools/pi_acceptance.py --offline` for software-only checks. It does not
contact integrations, the printer or systemd. Each result distinguishes passed,
failed and pending checks. Exit code 0 means no automated check failed; it does
not mean the physical checks are complete.

On the configured Pi, run these as the service user with the same environment as
the service. The commands read systemd state and optionally probe printer
connectivity; they do not reboot, restart, disconnect or print by themselves.
`--save` writes a private local report for later comparisons.

1. `python tools/pi_acceptance.py --phase baseline --probe-printer --save`
2. Reboot the Pi separately, then run
   `python tools/pi_acceptance.py --phase after-reboot --probe-printer --save`.
   This compares boot fingerprints and checks that the service is active/enabled.
3. Disconnect the printer separately, then run
   `python tools/pi_acceptance.py --phase disconnected --probe-printer --save`.
   The expected unreachable result counts as a passed disconnection check.
4. Reconnect it, then run
   `python tools/pi_acceptance.py --phase reconnected --probe-printer --save`.
5. Exercise service recovery separately (for example, stop/restart it during a test
   job), then run
   `python tools/pi_acceptance.py --phase after-recovery --probe-printer --save`.
   A changed process ID demonstrates restart, not the cause of that restart.
6. Temporarily choose a near-term daily print time in the web UI. After the new
   scheduled job sends a receipt and you physically collect it, run
   `python tools/pi_acceptance.py --phase scheduled --probe-printer --confirm-paper --save`.
   Restore your preferred daily print time afterward.

A phase is complete only when its automatic checks pass. `physical_complete` is
true only after all earlier phases are complete and a new scheduled outcome has
explicit paper confirmation. Unsupported or missing checks remain pending; the
tool does not infer paper delivery from a successful network write.

See [runtime reliability](../docs/runtime-reliability.md) for outcome tracking,
retry delays, sensor limitations and dependency upgrade policy.
