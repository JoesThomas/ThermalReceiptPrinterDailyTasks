# Tasks and exercises

Tasks opens the daily to-do checklist; the Exercises tab opens the exercise library. Routines & future plans leads to the existing scheduled routines, goals and wish lists.

Add, edit and remove local entries; complete or undo entries from either source. Google Doc source entries are edited in Google Docs, then refreshed explicitly or when a live receipt is generated. Web edits and completion marks do not write to Google Docs. The source uses the existing passwords.json google_docs.todo_url and random_url settings and the same text export access as the receipt.

To-do source lines still need a trailing full stop. Completed tasks are omitted from future receipts and their command triggers until undone; added local tasks can also trigger the same receipt commands. To-do completion persists. Exercises retain whole lines (including sets, repetitions and duration) and are fetched once per live run. Up to five are selected deterministically for the UK date and unchanged library; completing one does not replace it with a different exercise that day. Completion resets each UK day. Adding/removing exercises can change the daily selection. Entries selected for today's receipt are labelled in the exercise library.

Lists and completion records live privately in data/daily_lists.json, excluded from Git and included in private backups. File locking and atomic writes protect concurrent updates. Invalid saved files are preserved and require recovery rather than being overwritten with an empty list.

Generated therapy reminders and routine completion remain under their existing calendar and routines controls; they are not Google Doc source entries in this checklist. Saved receipt copies remain unchanged after completion.
