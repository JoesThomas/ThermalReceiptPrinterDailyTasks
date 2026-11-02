# Personal helper

Open **More tools → Personal helper** (`/helper`). The daily receipt gets a short **Your day** section: up to three priorities (two on a lighter day), the next saved departure, and at most two packing, preparation or errand prompts. Compact mode keeps the full task list in the web app. Calendar, bins, birthdays, vehicle dates and money warnings retain their existing sections. Turn the helper off or disable compact mode under Helper preferences.

## Task gaps and lighter days

Tasks come from the existing local/Google Doc checklist; completion updates that same checklist. Add an optional 1–480 minute estimate, home/outside/anywhere context, effort and essential flag. Appointments and known travel times are blocked before slots are suggested. Without an estimate, a task gets a **10-minute start**, or five minutes on a lighter day. This is a timebox, not an estimated completion time. Existing manual focus choices are preferred after essential/due tasks.

Suggested slots are not calendar bookings. Refresh Calendar and build Day travel after changing an event. Stale or mismatched routes are rejected. Missing travel gets a provisional 30-minute buffer which may be insufficient; missing event finish times block the rest of the planning day. Warnings keep provisional slot times off the receipt. The web page displays the assumptions for review. Events without locations reserve appointment time at home.

Lighter mode applies to today only: optional high-effort tasks are omitted, while essential and due items remain visible. The receipt notes additional urgent items if more than its priority limit exist. Repeated tasks preserve their existing recurrence rules.

Use task details to split a task into up to ten steps, complete steps, defer or hide a suggestion. Hiding does not delete the original checklist entry. Essential or due tasks remain visible even if deferred/hidden. Saving task details restores its suggestion. A task first observed at least seven days ago, or deferred on three different days, gets a gentle review prompt; it is never automatically deleted or marked complete. Observation starts on helper refresh or a daily receipt, not on ordinary page reads.

## Errands and things to take

Link a task to a shop/venue address. **Update helper & locate errands** runs a bounded background lookup for up to three unresolved addresses, reusing Day travel's confirmed places first. Ambiguous addresses remain unmatched. Locating a new address sends that address to the existing geocoding provider; page loads do not perform lookups.

Errands within approximately 300 metres of the geometry of a future walking/cycling/driving leg are shown as proximity suggestions. They are not added to your route and opening hours/detour time are not verified. Public transport legs are excluded from this comparison. Save an optional opening-hours note and check the itinerary before stopping.

Reusable rules match a case-insensitive part of an event title. Add things to take and preparation steps, with a 0–72 hour lead time. Preparation appears on its due day (or overdue while the event is still upcoming within 72 hours); future outings today get the relevant packing prompts. Phone/keys are suggested for outings; today's saved forecast can add rain protection at 40% rain probability and a warm layer at a minimum of 8°C or below. These are editable planning heuristics, not guarantees about conditions. Tomorrow's weather is never invented from today's forecast. A future outing tomorrow prompts charging a phone this evening.

## Kitchen planning

New generated meal plans gain a bounded preference for shared components and fresh ingredients within the existing allergy/diet/time/variety selection. Saved plans are not silently regenerated. Meals → **Use more, waste less** shows shared flavourings, component requirements and equipment-based washing-up estimates.

Explicit recipe amounts are combined only with compatible units. Missing amounts remain visibly incomplete; save an amount per recipe/component (e.g. `2 tbsp`) once to complete future totals. Requirement totals do not scale the component's preparation recipe or its yield automatically.

Perishable batches are separated conservatively using the existing component storage policy. Sunday's print directs later batches to preparation closer to use rather than suggesting keeping a Sunday batch all week. The usual storage/leftovers guide remains authoritative and times start at actual preparation; shorter ingredient/pack instructions still apply. Washing-up estimates count likely equipment, not wash cycles or minutes; raw-food equipment must be cleaned before reuse.

## Local data and privacy

`data/personal_helper.json` contains helper preferences, task observations/steps, packing rules, errand addresses/points, a small weather summary and recipe amount overrides. It is bounded, validated, locked and atomically written with owner-only permissions. Corrupt state is not replaced automatically. It is gitignored and excluded from the ordinary allowlisted JSON backup, like the Day travel itinerary. Include it in your own protected local backup if you want it restored.

All helper pages/actions require the application's login; writes also use its CSRF protection and private no-store responses. No credentials are added here. Nothing sends messages, tracks live location, books appointments or changes your calendar.
