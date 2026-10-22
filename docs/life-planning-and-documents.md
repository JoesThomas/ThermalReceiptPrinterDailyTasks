# Cash pots, organisation and encrypted documents

Update with `git pull`, install the new release dependencies with
`python -m pip install -r requirements.lock`, then restart Receipt Control.
The navigation now includes **Organiser**, **Tax & annual funds**, and **Documents**.
No bank account is created and no payment is initiated by these tools.

## Tax and annual expenses

Enable priority funding after checking the balances. The Tax reserve is first;
other annual pots follow their numbered priorities. All suggestions use cash
already available after bills, Amex statement protection, everyday spending and
bank reserves. A job or salary is not required to fund these cash pots. The
existing salary requirement for investing spare bank cash is unchanged.

Tax can use the existing supported rental-tax estimate or a manual total still
payable **after PAYE and other withholding**, minus tax already paid. Do not add
the rental estimate again to a manual total that already includes it. The rental
estimate remains limited to its supported tax year and scope; net salary is not
used to infer a tax band. Set the estimate-check date and review assumptions when
income changes. These are estimates, not tax advice or a submitted return.
The funding deadline is a savings goal. Automatic mode defaults to the supported
tax-year end if no deadline is given; it does not claim that this is an HMRC
payment deadline. Check the actual deadline on your tax account.

The existing rental-tax reserved amount and Tax reserve balance describe the
**same pot**: the larger amount is used, rather than their sum. Update both when
paying tax or reducing the reserve. Enabling these pots changes protection from
reserving the full estimated liability immediately to protecting the money
already earmarked and prioritising the monthly funding gap. Any remaining gap
is shown explicitly. Disabling the new tax pot retains legacy tax protection.

For every pot, indicate whether its balance is already included in selected
HSBC/Monzo cash. Included money is protected as an earmark. Outside savings are
not deducted again. Pot balances are planning labels over your actual accounts,
so they are not added to net worth a second time. Link the exact scheduled bill
name (or use the same pot name) to avoid reserving both an included earmark and
that same forecast bill. The full dated bill remains a cash cost; its linked
hold stays protected until the period containing the payment. Pots do not add a
second copy of a bill to the forecast. Recheck balances after spending from a pot.

The page shows the target, reserved amount, gap, monthly need and affordable
contribution in priority order. The remaining amount and recent spending pace
are shown only with fresh, complete bank data and a future payday. Suggestions
are based on recorded costs and can change with unlisted payments or new spending.
Test-finance scenarios protect held pots and linked bills; future monthly pot
contributions remain suggestions, not assumed completed transfers or new income.

Record a completed earmark/transfer only after doing it. Repeated requests cannot
credit the same suggestion twice. External transfers stay protected while pending
bank matching, so stale bank balances cannot free that cash for spending again.
After refreshing Finance, choose the correct posted debit and explicitly verify
the recipient. Amount/date matches alone do not prove the destination. One bank
debit cannot be matched to two completed transfers. No automatic bank movement or
silent transaction classification is performed. Update targets and dates for the
next annual cycle after paying an expense; balances are never reset automatically.

## Organiser and receipts

Use dated items for replies, decisions, refunds, deposits/money owed, job
applications and documents to bring. For applications, use the title for the
employer/role and notes for the current stage/next action. Add one item per
assessment, interview or follow-up deadline, or move the follow-up date forward.
Complete, defer, reopen, edit or drop items in the web app. Receivables never
count as spendable money before an actual bank receipt.

Daily action receipts show due or overdue items. Sunday reviews include the next
seven days, the next few appointments and a prompt to close or defer old work.
Cash-pot shortfalls approaching their deadlines are printed when relevant; fresh
finance data can also show the remaining daily spending budget. A stale finance
snapshot never becomes a fresh daily balance merely because the receipt prints.
Old saved receipts retain their original information.

Calendar overlap checks consider all overlapping timed events, including a long
event spanning several shorter events. Different locations with a short gap
produce a travel-buffer warning. This is a configurable minimum, not a routing
or traffic forecast. Missing end times are never guessed. The web screen labels
its cached calendar check time; open Calendar to refresh. Receipt checks use the
calendar events retrieved for that receipt.

## Document security and setup

This version uses the existing single household account. Every upload, preview,
download, deletion and encrypted-backup request requires sign-in and a separate
15-minute document unlock using the app password. Existing CSRF protection and
login throttling cover the new forms. Locking or signing out removes access from
that session. No public document URLs or share links are created.

First unlock Documents, then initialise storage. Files and the title/index are
authenticated-encrypted with Fernet. Blob encryption binds each file to its random
ID, detecting swapped files as well as tampering. The store is
`data/document_vault/`, outside the web/static directory, owner-only. Neither it
nor the key is committed to Git or included in diagnostics/settings backups.

The key defaults to `~/.config/receipt-control/vault.key`, outside the project.
Set `RECEIPT_VAULT_KEY_FILE` before starting the app to use another dedicated,
owner-only directory outside the project. Key files must be owned by the service
user with permissions 0600; key directories should be 0700. Existing shared
parent directories are not chmodded. Back up the original key separately and
securely. The app never sends its contents to the browser. Losing it prevents
recovery; a missing key with existing encrypted data is not silently regenerated.
This protects copied stored files, not a compromised running server with access
to the key, and is not a multi-user permission system.

Allowed uploads are PDF/JPEG/PNG, at most 5 MiB, 100 documents/100 MiB total. The
extension and parsed format must agree. Parsing runs in a disposable process with
CPU/memory/time limits. Images are re-encoded without metadata. Active PDF
actions, forms, embedded files and external links are rejected; flatten/export a
passive copy if needed. PDFs are attachment-only; only normalised images have an
inline preview. Format checks are **not antivirus scanning**. Download names are
generated, and responses prevent caching, content sniffing and active content.

Flask multipart files stay in bounded memory rather than plaintext temporary
files. The bundled Waitress launcher raises its input/output spill thresholds
above the permitted plaintext document size and bounds request bodies at 6 MiB.
If you use another server or TLS proxy, configure it not to spool plaintext
document uploads/downloads to disk and limit request sizes. Those external
components are not configured by this repository.

## HTTPS and access from other devices

Local loopback HTTP continues to work. Plain HTTP from a non-loopback address is
rejected, including sign-in. Use HTTPS from other devices. Behind a TLS reverse
proxy on this same machine, bind Waitress to `127.0.0.1` and explicitly set
`RECEIPT_TRUST_PROXY=1`. Only loopback proxy connections may supply the scheme;
forwarded headers from direct LAN connections are not trusted. The proxy must
overwrite the forwarded scheme correctly, terminate valid TLS, and disable
plaintext body buffering. Secure cookies are used on HTTPS and HSTS is enabled.
Do not expose the loopback backend port as an unprotected proxy endpoint.

## Backups, retention and recovery

The ordinary private backup includes organiser/fund records and random document
links, but not document files, document titles/index or the key. Download a
**separate encrypted document backup** from the unlocked Documents page. It
contains only encrypted files and an encrypted index. Keep the original key in a
separate secure backup. Downloaded backup retention is your responsibility: live
deletion cannot erase an offline copy. A document retention date removes the live
copy on the next document access; the UI explains this distinction.

Recovery uses an empty vault and the original external key. Stop the web app,
restore the key with owner-only permissions, then run:

```sh
python tools/document_recovery.py /path/to/encrypted-documents.zip
```

Recovery rejects unexpected paths, duplicate archive entries, compressed/oversized
archives, tampered files and non-empty stores. Existing live documents are not
overwritten. Expired documents are removed after recovery. Review links in
Organiser after deleting/expiring a document: unavailable IDs do not grant access
to a replacement document. The receipt prints the reminder you entered, never
uploaded document contents.

Implementation references:

- [OWASP file upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [Cryptography Fernet](https://cryptography.io/en/stable/fernet/)
- [pypdf security limits](https://pypdf.readthedocs.io/en/stable/user/security.html)
- [Waitress buffer settings](https://docs.pylonsproject.org/projects/waitress/en/latest/arguments.html)
