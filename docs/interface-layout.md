# Control interface layout

The home page is a compact dashboard: saved receipt, print action, latest print status in UK local time, next 03:00 print slot (while the server runs), location and routine count. It does not fetch bank transactions for these tiles.

Shared navigation leads to Receipt, Finance, Tasks, Meals, Calendar and Settings. Receipt, Tasks, Account settings and Settings use focused views of the existing control route. Finance includes links to account editing and savings history. Form submissions return to their relevant view; older in-page anchors are routed to the matching view in the browser.

Account editors show readable name/amount rows and expand into their existing forms. Receipt settings use native disclosures for secondary controls, with all fields retained in the form. Browser validation opens any collapsed parent containing an invalid field. Without JavaScript, the original forms remain visible and usable. The receipt preview retains its paper width, monospace text and printed graphics.

Shared styling uses a neutral background, one green accent, subdued labels and borders, consistent field spacing, and responsive single-column forms on narrow screens. Keyboard users have a skip-to-content link and visible focus states. No external fonts, chart services or new frontend dependencies are required.
