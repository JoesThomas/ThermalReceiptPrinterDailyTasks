# Vehicle dates and cover details

Open **Vehicles** in the web interface to add each vehicle's registration, optional name, MOT expiry, tax due date, insurance expiry and breakdown expiry. Insurance and breakdown providers, policy or membership references and notes are optional. Leave unknown dates blank. Past dates are permitted so overdue reminders can be recorded. Up to 20 vehicles can be stored.

Records are saved locally in private, gitignored `data/vehicles.json`. Editing and removing records uses file locking and atomic writes with owner-only permissions. Invalid dates or duplicate registrations do not replace saved data. A damaged file is reported and preserved. Private backups, restores and update checkpoints include the records.

The Actions receipt prints the four recorded dates and any saved cover details for each vehicle. Dates due today, within 31 days or already past are labelled using the London date. The values are manual reminders, not confirmation that insurance or breakdown cover is active. No API key or internet connection is needed for these records.

Existing Sunday DVLA checks remain available for vehicles configured in private configuration that are not also maintained locally. A locally saved registration takes precedence, avoiding duplicate vehicle sections. Changes mark saved Actions previews as outdated; generate a fresh receipt after editing.
