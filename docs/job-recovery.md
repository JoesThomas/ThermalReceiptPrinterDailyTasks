# Receipt jobs and recovery

Receipt Control supervises web prints, scheduled prints, archive reprints and live previews. Each newly started job has a ten-minute generation limit. Cancellation and timeout send TERM to the isolated receipt process group, then KILL if it does not stop within five seconds. The worker records the result and releases the lock after cleanup. Completed workers are reaped by the server.

A shared panel on every authenticated page shows the current section, completed sections, elapsed time and job ID. Cancel requests require authentication and CSRF validation; the server verifies the worker command and process group before signalling it. Cancellation does not delete saved receipts or undo paper already printed. Check the physical receipt before using Retry print; jobs are never automatically retried.

The Receipt navigation opens the latest preview. Receipt options edits what will be generated; Past receipts opens the archive. These operations stay separate so reviewing a saved copy never starts a print.

Print and preview logs include UTC timestamps, job IDs and section changes. Local receipt timestamps continue to use Europe/London. Progress counts completed sections rather than estimating remaining time.

These safeguards apply to jobs started after updating. An existing old worker may still require cancellation. Direct terminal invocations of main.py are outside the web supervisor. The process-group cleanup targets macOS and Linux; run one Receipt Control server process, as the start mutex is process-local. Graceful web-server restarts do not remove a running job's timeout supervisor.
