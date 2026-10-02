# Private receipt history and simpler finance review

Every newly generated live preview and physical print is captured locally in
`data/receipt_archive/`. Earlier receipts cannot be reconstructed automatically.
The archive uses UK dates for filtering, shows the original generation time,
and includes only pages actually produced by that run. Individual archived pages
can be reprinted, or a new version can be generated with current live data.
Reprinting uses saved text and graph images; it does not fetch fresh records or
repeat finance bookkeeping. The archive has no automatic deletion policy.

Source checks shown in previews and the archive record when collectors returned.
A checked feed may still be incomplete. Bank coverage is explicitly labelled;
manual savings/investment valuations retain the dates in balance history.
An absent source check is not evidence that the source was refreshed. Archive
write errors are logged without failing an otherwise completed physical print.
Printed styling beyond captured text alignment and images is not preserved.

The finance review begins with current cash, dated payments in the next 30 days,
last-30-day income and accessible savings. Transaction lists and secondary charts
are expandable. Forecast assumptions identify manual versus bank-derived everyday
spending. The calculation itself is unchanged: no future income is assumed,
unknown payment dates and incomplete bank records can limit the forecast.
Successful empty gig searches are omitted from the paper receipt. Unavailable or
partial search results still carry a notice.

## Backup and restore

The Private backup link downloads a bounded JSON file of allowlisted local data:
receipt settings, commitments, finance settings/categories, savings/investments
and valuation history, routines, future tasks, wish lists and local food records.
Passwords, API keys, OAuth tokens, bank transaction caches, generated receipts and
recipe source files are excluded. Copy `data/receipt_archive/` separately when
moving computers. Keep backups private: they contain personal information.

Restore requires authentication, CSRF protection and a second confirmation of the
filenames being replaced. It replaces only included files, leaves other local
files unchanged, and waits for active web receipt jobs to finish. Uploads are
limited to 900 KB, supported filenames and expected top-level JSON shapes;
non-finite numeric values are rejected. It is not an importer for arbitrary files.
Per-file writes are atomic; an I/O failure restores preceding bytes. Before writing,
`data/private_backups/` receives a private rollback record containing original file
contents, with null for files that did not exist. A process or power failure during
multi-file replacement can still require recovery from that record. Staged restore
files expire after 15 minutes and are cleaned on subsequent uploads. Cancelled
uploads are not applied. These runtime directories are excluded from Git.

Updates do not copy any private runtime data into the public repository.
