# Weekly review and Quick Print

- **Home → Weekly review** shows seven days of saved appointments, planned
  bills, vehicle renewals, organiser follow-ups and meal shopping. It flags
  calendar overlaps, short travel gaps and local shop visits on the same day as
  appointments. A visit has no fixed time, so this is a prompt to check timing.
  Calendar coverage and forecast assumptions are labelled. Sunday’s Actions
  receipt prints at most two review items; other days keep the usual follow-ups.
- **More tools → Quick Print** prints text as a separate receipt. Add an
  optional centred title, and preview before sending. Tick boxes apply to
  non-empty receipt text lines only; the title never gets one.
  Open **Quick Print settings** to edit the body character limit (default 20,000,
  supported range 1–100,000). The title still has its separate 120-character limit.
  The live counter flags long drafts; preview shows the actual wrapped line count
  and suggests trimming, splitting or reading on screen above 80 printed lines.
  This is advice, not the former 80-line block. Saving a limit keeps the draft,
  including when it is longer than the new limit. Preferences are stored locally
  in the private, Git-ignored `data/quick_print_settings.json` file.
  Wrapped lines continue under their original item. Quick Print uses the
  configured paper width and existing printer status; it does not enter the
  receipt archive. The worker uses a private temporary spool file that it
  removes when consumed or when the job ends.
- **Monthly meals & shops → shopping checklist** has a phone mode. Got it,
  Already have and Couldn’t find are saved in the current browser for the exact
  ingredient list. They do not change the menu or the independent paper list.
- **Meals → Use this first** records portions and shows possible dinner
  alternatives for a chosen date. It uses current household preferences,
  recipe identity, portion count and conservative storage windows. It does not
  certify storage or change the meal plan; record portions used manually.
- **Finance → Bill price history** preserves the actual payment and asks
  whether to keep or update the future estimate. See [Finance](finance-understanding.md).
