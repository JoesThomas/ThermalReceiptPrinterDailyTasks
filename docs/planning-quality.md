# Saved plans, explanations and settings recovery

## Named finance scenarios

Test finance can save up to 50 named sets of manual inputs. Enter a scenario name
and choose **Save named scenario**. Reusing a name (ignoring case) replaces that
scenario's inputs. Loading fills the form without a bank lookup, calculation or
print. Review dates, starting balances and account destinations before generating;
old dates remain visible and must be updated if the scenario is now in the past.
Deleting saved inputs does not delete previously generated receipts.

Inputs are allowlisted: CSRF tokens, unrelated form fields, bank credentials and
raw bank transactions are not saved. Unchecked options stay unchecked. These
owner-only records are included in the existing private settings backup.

## Transfer explanations

After generating a test, expand **How the transfers were worked out**. This uses
the recorded first-period allocation, not a separate calculator. It shows income,
starting bank cash, reserves, bills, spending, extra repayments, savings and the
cash left above reserves. Scheduled savings are included in bills; the physical
cash top-up uses a separate protected reserve. Neither is an extra deduction.

Spare bank cash remains subject to the salary gate and selected strategy. Other
income can still support ordinary allocations when salary is absent. A shortfall
is labelled explicitly. This is a planning estimate and does not move any money.
The printed receipt stays compact; this explanation is on the web page.

## Settings recovery

Settings are validated before use and before saving. Legacy partial settings
continue to use defaults for omitted fields. Saving writes a versioned settings
file and a last-good copy. Damaged settings are never overwritten by a page read.
The web interface displays a warning; last-good values are used where available.
Automatic printing and one-shot requests are paused during recovery. Review the
settings and explicitly save them to resume normal operation. If no valid copy
exists, the warning explains that review is needed before relying on defaults.

An explicit save first preserves damaged content in an owner-only
`receipt_settings.invalid-<timestamp>-<identifier>.json` file. A file with a newer
schema version is not downgraded by this application. Use a compatible version
of the app to edit it. The last-good copy is included in private backups; damaged
copies are left locally for recovery and are not part of routine backups.

## Receipt version details and storage upgrades

New archive entries include the application Git revision (or
`RECEIPT_APP_REVISION` for deployments without Git), the effective receipt settings
fingerprint, the local finance configuration fingerprint for finance receipts,
and a scenario-input fingerprint where applicable. The archive details page
shows these under **Receipt version and configuration**. Configuration is sampled
at archive time; hashes identify changes without storing the source contents.
These identifiers are useful for comparisons, not a complete replay of live data.
Older receipts remain readable and show that version information is unavailable.
Restart the web app after installing an update so its cached revision is current.

Receipt settings, savings goals and archive retention settings now use explicit
schema version 1, as do named scenarios and newly archived receipts. Legacy data
is upgraded in memory without changing files on read. Edits write the current
version. Unsupported future versions are rejected before edits; user balances,
account identifiers, dated entries and pins retain their existing structure.
