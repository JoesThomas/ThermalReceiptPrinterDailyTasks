# Day travel planner

Open **Calendar → Plan a day's travel**, or **More tools → Day travel**. The planner
is private to the signed-in web app and does not add anything to daily receipts.
It combines the selected day's personal calendar and enabled Villa fixtures,
using the same local calendar location corrections. It does not write to Google
Calendar. Dates and displayed times use Europe/London, including BST.

## Plan a day

1. Choose a date (up to one year either side of today).
2. Save your **home address**, usual travel mode, whether your car starts at home,
   arrival buffer, minimum useful time at home and parking allowance.
3. Choose **Find calendar locations**. This explicitly retrieves that day's
   calendar and looks up previously unconfirmed addresses. It runs in the
   background with progress rather than holding a web request open.
4. Confirm the correct map point for home and each destination. Place names can
   be ambiguous: the first search result is never silently accepted. Choose a
   result or enter latitude/longitude manually. A postcode may represent an area,
   not an exact front door. Home can be entered manually without online lookup.
5. Choose **Build travel plan**. The numbered mini map and journey cards show
   the suggested order, departure/arrival estimates and whether a home stop fits.
   **Load street map** loads the optional background map; pins and route lines
   work without it. Map zoom is available using its buttons/keyboard.

The planner preserves event order; it does not reorder appointments. To change an
address use the calendar's local location correction, then find locations again.
For an online event select **Exclude from travel plan**. All-day/untimed events
remain visible but cannot be assigned a reliable journey order: edit them to have
start and finish times in the calendar. A missing finish time is explicitly flagged;
you may enter a local finish-time override without changing the calendar. A finish
earlier than the start is interpreted as the following day.

## Home stops and the car

The day is assumed to begin at home. Before each later event the planner compares
travelling directly with returning home and going out again. It includes both
journeys, driving parking allowances, the next event's arrival buffer and your
minimum useful time at home (30 minutes by default). It suggests a home stop only
when all necessary durations and the preceding event's end time are known and
the stop fits. You can force a direct journey or prefer a home stop; an impossible
or unverified home preference produces a warning rather than claiming it fits.
Late journeys depart no earlier than the preceding event ends, and conflicts or
buffer shortfalls are flagged. Durations round up, while available home time
rounds down. These are estimates, not guarantees about arrival.

Driving moves the planned car location. Walking, cycling and public transport
leave it parked where it was. If a later driving journey starts elsewhere, the
plan adds a walking leg to collect the parked car before driving. If no car was
available at the start, it suggests walking instead and says so. A taxi/lift is
not treated as your own car. Cycling assumes you already have a bicycle with you.
These are planned movements, not live GPS or proof that you actually took a journey.
Review any change of plans, overnight event, or day that did not start at home.

## Routes and public transport

Driving, walking and cycling estimates use the respective FOSSGIS/OSRM routing
profiles over OpenStreetMap data. Driving does **not** include live traffic;
your parking allowance is added to each nontrivial driving leg. The public
service is best-effort, not a production service-level guarantee. Solid map lines
are returned street routes. Dashed lines connect known endpoints only; they must
not be followed as road or walking instructions.

The app does not invent bus/train schedules. Use **Check directions and the
timetable in Google Maps**, choose the appropriate date/time there, and optionally
save a checked one-way duration locally. Include walking, waiting and changes in
a public transport duration. Reverse journeys need their own entry. A driving
override represents journey time; the separate parking allowance is still added.
Manual estimates override provider times until removed. Saved overrides are
listed and removable. An unknown route/duration remains unknown, never zero,
and cannot prove that a home stop fits. Keep timings up to date before relying
on a manually entered transit duration.

## Privacy, providers and limits

Nothing is geocoded or routed just by opening this page. **Find calendar
locations** sends location text (including your home) to Photon/komoot. **Build
travel plan** sends confirmed coordinates to FOSSGIS. Event titles and calendar
feed URLs are not sent to either provider. Clicking a Google Maps directions link
shares its endpoints with Google. Loading the street-map background sends the
viewed map tiles and the site's origin to OpenStreetMap; it does not send page
query strings or calendar titles. Provider logs cannot be deleted by this app.

Home, confirmed places, manual durations and at most 31 selected day snapshots
are kept in `data/day_travel.json`, with owner-only files, authenticated routes,
CSRF checks and no-store responses. Provider caches use hashed filenames under
`cache/day_travel/`, also owner-only. These files are ignored by git and excluded
from ordinary backups and receipts. They are not separately encrypted like the
smart-home credential vault: protect the host and use private HTTPS/VPN access.
**Clear travel data** deletes the local settings, day plans and provider JSON
cache. Wait for an active job to finish before clearing; separate copies and
external provider logs remain outside the app's control.

Up to 30 events per day, 200 saved places and 500 directional duration overrides
are supported. Network responses, timeouts and a two-minute lookup budget are
bounded. One background planner per installation is allowed; the page polls only
small progress data tied to its login session. Geocoding results are cached for
30 days, routes for one day; cache files are capped at 500. No live location
tracking, automatic background polling of providers or bulk address searches run.

Providers are used at a maximum of one network request per second across the
installation, with an identifying User-Agent and visible attribution. Public
endpoints are intended for modest personal use and may throttle or become
unavailable. Admins can change `RECEIPT_TRAVEL_GEOCODER` to a compatible HTTPS
Photon base and `RECEIPT_TRAVEL_ROUTER` to a compatible HTTPS FOSSGIS-style base
(with `/routed-car`, `/routed-foot`, `/routed-bike` paths), without editing code.
Configuration belongs on the trusted server, not in user-supplied URL fields.

Sources and terms:

- [Photon public demo and self-hosting](https://github.com/komoot/photon#demo-server)
- [FOSSGIS routing privacy and usage](https://routing.openstreetmap.de/about.html)
- [OpenStreetMap tile usage](https://operations.osmfoundation.org/policies/tiles/)
- [Google Maps URL directions](https://developers.google.com/maps/documentation/urls/get-started)

Leaflet 1.9.4 is vendored locally under `web_control/static/vendor/leaflet` with its
BSD-2-Clause license. The JS/CSS SHA-256 hashes match the official Leaflet download
page. No third-party JavaScript CDN is required at runtime.
