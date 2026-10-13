# Prepared updates and rollback

Run `python tools/update_project.py prepare origin/main --fetch` from the existing
checkout. This creates a private checkpoint under `data/updates/<id>`, a detached
candidate worktree and a pinned runtime environment at a permanent path within
that checkpoint. It installs `requirements.lock`, compiles the candidate, runs
its offline installation/dependency checks and validates supported settings
against its schemas via stdin. It does not switch live code, print, fetch bank
data, change settings, or restart the service. Preparation refuses tracked local
edits. Review the printed previous/target revisions and checkpoint before applying.
Use trusted repository revisions; candidate validation executes that code.

Run the helper as the checkout/service owner so the service can read its private
environment and checkpoints. Avoid preparing as root when the service runs as
`receipt`. A simple Pi workflow is to stop/start the service separately with
`sudo systemctl stop receipt-control` and `sudo systemctl start receipt-control`,
while applying as the service user with `--stopped`.

On a Pi where that user already has permission to manage `receipt-control.service`, explicitly
run `python tools/update_project.py apply <id> --service`. The helper stops that
service, checks that receipt workers have stopped, takes a fresh settings
checkpoint, validates current settings again, switches the clean checkout and
activates the prepared environment through `.venv`. It starts the service and
checks its active state. If activation fails, it attempts to restore the previous
revision, environment and exact settings bytes. A recovery failure is reported
explicitly and the checkpoint is retained; keep the service stopped until repaired.
This service-state check does not prove integration health or physical printing.

On macOS or a manually managed server, stop the app and workers yourself, then use
`python tools/update_project.py apply <id> --stopped`. Start it yourself afterward.
The helper cannot stop an arbitrary manually started web process; `--stopped` is
your explicit assertion that it is stopped. Reactivate your shell environment
with `source .venv/bin/activate` after applying or rolling back.

The working checkout is switched to a detached commit. The helper does not push,
rewrite remote Git history or discard tracked edits. Ignored and untracked files
are protected during checkout. Candidate code and current Git revision must still
match their prepared state; otherwise prepare a new candidate.

## Rollback

Use `python tools/update_project.py rollback <id> --service` (or `--stopped`).
Rollback validates the previous code/environment against **current** supported
settings and retains those settings by default. If newer settings cannot be read
by the older revision, it refuses the rollback before switching.

`--restore-settings` explicitly restores the exact pre-update supported settings
and removes supported files that were originally absent. This can replace edits
made since the update. Current settings are saved first in `before-rollback.json`.
If a rollback fails after switching, the helper attempts to return to the applied
code/environment and current settings; incomplete recovery is clearly flagged.

Checkpoints are owner-only and include the existing supported backup allowlist,
not credentials, transaction caches or the complete receipt archive. The backup
size limit is 900 KB. Linked settings files or unsupported/oversized data require
a manual update workflow. Existing credentials and other untracked runtime data
stay in place. Do not remove an active update checkpoint: it contains the active
virtual environment, candidate worktree and recovery files. Never prune these as
ordinary receipt archives. Physical restart/reboot checks remain in the
[Pi acceptance guide](README.md#repeatable-acceptance-reports).
