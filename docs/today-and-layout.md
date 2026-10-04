# Today dashboard and receipt layout

Home uses local saved information for appointments, tasks, today’s workout and pending deliveries. Task and exercise completion, and delivery confirmation, can be updated there. Google Calendar is refreshed during live generation or when opening the calendar page; Home does not fetch it. Old calendar checks are labelled. Delivery dates and wording are saved notices, not a live courier feed. Confirmed deliveries stay off new receipts, with received history and undo on the Deliveries page. Historical receipt copies remain unchanged.

Data freshness lists the latest source check available in saved receipt captures, in UK local time. A check timestamp is not a forecast observation timestamp. Weather and calendar checks and bank availability are also printed alongside their receipt pages. Unavailable bank data remains explicitly marked.

Changes compare consecutive generated receipts, including previews. Only generated pages replace their baseline: tasks and delivery timings on Actions, and paid bank-match rows on Finance. No finance comparison is made when bank data is unavailable. The first relevant page establishes its baseline. This is a convenience comparison, not a full financial audit. Dashboard caches are private and excluded from Git.

Settings → Receipt layout leaves the original Information, Actions, Food, Finance order by default. Each page must appear once in a custom order; finance still requires its existing trigger. The default streams as before. Custom ordering buffers page rendering, collects the selected pages, then sends them in the chosen order, so paper output starts later. A failure during sending may still leave partial paper. Saved previews preserve the order used to generate them; archive reprints preserve their stored page order.

Compact detail uses compact weather and at most two headlines per news section. It retains task text, exercise sets/reps/duration and finance amounts. Detailed preserves existing weather auto/full/compact settings. No automatic essentials-first ordering is applied.

Successful physical jobs say “Sent to printer”. ESC/POS socket/USB writes do not prove that paper was printed. Preview generation is labelled separately. Real printer output must still be checked on the device.
