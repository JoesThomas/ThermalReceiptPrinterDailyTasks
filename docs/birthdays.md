# Birthdays

Open **Birthdays** in the web interface to import a CSV, add a birthday, correct an entry, remove it or download the current list. After updating the application, import your cleaned `birthdays.csv` here, then generate a fresh Actions receipt.

Records live in private, gitignored `data/birthdays.csv`. Imports accept `Name,Year,Month,Day` and an optional `ID` column. Unknown years remain blank. Saved exports include stable IDs so editing a name does not change the record's identity. Web edits write the same CSV atomically with owner-only permissions and a file lock. Backups, restores and update checkpoints include the list.

Imports validate calendar dates, birth years and duplicate identities. Completely blank rows and exact duplicates are removed. Invalid or conflicting records reject the whole import without changing saved data. Re-importing an older file cannot silently overwrite web edits. Use distinguishable names when adding people who share a name. Older CSVs with a Link to Profile column are accepted, but the links are discarded. Validation checks consistency; it cannot independently confirm a person's actual birthday.

The Actions receipt includes today's birthdays and the following seven days, using the London date. Ages appear only when a birth year is known. Up to ten birthdays are printed, with a reminder to check the web list if there are more. No empty birthday section is printed. February 29 birthdays appear on February 29 in leap years; another celebration date is not assumed.

The home page also shows upcoming birthdays. Changed records mark saved Actions previews as outdated. Personal birthday records are never included in the repository.
