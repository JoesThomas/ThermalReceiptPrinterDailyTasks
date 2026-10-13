# Diagnosing private backup warnings

The older `Private backup unavailable; check local data and disk space` warning did not identify the cause. It could also describe a failure in a different maintenance job. It is not evidence that the disk is full.

Open **Private backup & restore** and choose **Save snapshot now**. This retries immediately, even during an automatic retry delay. A failed export names the supported file when JSON or data validation fails, and gives specific guidance for permission, full-disk, quota or read-only filesystem errors. Existing snapshots and source data are retained; invalid files are not skipped to manufacture a successful backup. A restore drill passing for an older snapshot does not mean the latest creation attempt succeeded.

For `receipt_settings.json` and its last-good copy, the diagnosis also includes the safe settings validator reason, such as an invalid daily print time or a duplicated receipt page. Fix only the identified setting; no automatic reset is performed. If the app is using recovered settings, review them before saving: an explicit save preserves the invalid original under its existing `.invalid-...json` name. A file from a newer schema needs the matching application version rather than a downgrade or reset.

For an invalid weather detail value, use `python tools/check_private_backup.py --repair-weather-detail`. This explicitly changes only `display.weather_detail` in the current receipt settings to `full`, retaining all other stored keys and preserving the original bytes in an `.invalid-...json` copy. Other invalid settings or a newer schema block the repair before any settings write. The command then runs the read-only backup check; use **Save snapshot now** to verify that a new backup can be written. The last-good file is not overwritten by this targeted repair.

For a read-only check from the project folder, with the app's Python environment active:

```sh
python tools/check_private_backup.py
```

The check validates local data and reports free disk space if validation succeeds. It prints no task text, balances, credentials or raw exception messages, writes no files and does not test actual backup writes. Use **Save snapshot now** to verify write access. Share only the safe diagnosis, not the private JSON contents, when investigating a compatibility problem.

Automatic failures retry after 15 minutes. The maintenance loop remembers this delay even if a full disk prevents saving its status file. An unchanged warning is logged at most once an hour while the process runs; a different diagnosis is logged immediately. Other maintenance tasks continue independently and report their own stage if they fail. Successful recovery clears the failure state. A new installation with no supported data remains idle without a failed-backup warning.

Latest attempt metadata is in `data/backup_attempt.json` and appears on the backup page and Home attention panel. It contains only the safe diagnosis and operational timestamps and is excluded from exported private settings. Automatic snapshots retain the 900 KB limit, bounded reads and supported-file allowlist. Linked source files are rejected rather than following them into another location.
