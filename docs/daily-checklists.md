# Tasks and exercises

Tasks opens the daily to-do checklist; the Exercises tab opens the exercise library. Routines & future plans leads to the existing scheduled routines, goals and wish lists.

Add, edit and remove local entries; complete or undo entries from either source. Google Doc source entries are edited in Google Docs, then refreshed explicitly or when a live receipt is generated. Web edits and completion marks do not write to Google Docs. The source uses the existing passwords.json google_docs.todo_url and random_url settings and the same text export access as the receipt.

To-do source lines still need a trailing full stop. Completed tasks are omitted from future receipts and their command triggers until undone; added local tasks can also trigger the same receipt commands. To-do completion persists. Exercises retain whole lines (including sets, repetitions and duration) and are fetched once per live run. Up to five are selected deterministically for the UK date and unchanged library; completing one does not replace it with a different exercise that day. Completion resets each UK day. Adding/removing exercises can change the daily selection. Entries selected for today's receipt are labelled in the exercise library.

Lists and completion records live privately in data/daily_lists.json, excluded from Git and included in private backups. File locking and atomic writes protect concurrent updates. Invalid saved files are preserved and require recovery rather than being overwritten with an empty list.

Generated therapy reminders and routine completion remain under their existing calendar and routines controls; they are not Google Doc source entries in this checklist. Saved receipt copies remain unchanged after completion.

## Planning tasks and workouts

Tasks have optional due dates, high/normal/low priority and daily/weekly repeats. Today includes undated and overdue tasks; future dated tasks are in Upcoming and stay off new receipts until due. Completing a repeating task schedules its next occurrence from the completion day. Source document text remains read-only; its dates and priorities are private local overlays.

Exercises separates today’s workout from the library. Progress counts today’s selected exercises, excluding those skipped. Save available equipment, then select **Suggest workout with my equipment**. Suggestions use up to five exercises already in your library. Recognisable equipment names (including dumbbell curls and rowing) provide initial requirements; edit each exercise’s options to confirm all required equipment. Unfamiliar source exercises without confirmed requirements are excluded. With equipment settings saved, subsequent daily selections also use these requirements. Manual selections can override the equipment filter.

Sets, repetitions and duration are optional instructions you enter; the app does not prescribe training intensity. The saved daily selection appears on new receipts. Skip lasts for one UK day and can be undone in the library. Completion history retains the last 90 completed dates per exercise. Editing or removing an exercise can change the current selection. Equipment, plans and history are included in the existing private checklist backup and are never committed to GitHub.
