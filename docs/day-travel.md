# Automatic day travel planner

Open **Calendar → Plan a day's travel**, or **More tools → Day travel**. Enter your
home once, select a date, then choose **Plan my day**. A background job retrieves
that day's calendar, locates addresses, compares journeys and builds the map.
The main workflow does not require coordinate confirmation or manual durations.
No network-heavy planning runs merely because the page was opened.

## Automatic locations

The planner tries the full calendar address, then street-address variants if a
long venue name prevents a match. It prefers matching postcodes/house numbers.
If no building match is available, UK postcode lookup can provide an approximate
postcode centre. This is clearly labelled: it is not claimed to be an exact door.
Ambiguous distant matches or conflicting house numbers are not silently chosen.
An unresolved address remains unknown, rather than inventing a route.

Saved manual map corrections are preserved. Optional corrections and coordinates
are under **Advanced: review or correct automatic locations**. The street map now
loads automatically with the plan; numbered pins match the location list.
Calendar location corrections still apply, and no calendar events are changed.

## Walk when practical, otherwise check public transport

**Automatic · walk when practical** is the default. Walking is preferred up to
25 minutes (editable), provided it fits the time before the next appointment.
Otherwise the planner checks scheduled bus/train journeys. If no usable public
transport journey is returned, it can fall back to the available car, collecting
it on foot first if it was parked at an earlier stop. A long walking fallback is
labelled for review. Walking or transit does not move the planned car location.
You can still explicitly choose driving, walking, cycling or transit in preferences
or for an individual event. Cycling assumes a bicycle is available.

The planner uses the next event's arrival deadline, including your arrival buffer,
and rejects transit departures before the previous event finishes. Return trips
are requested for leaving after the event. Bus/train departure times are actual
returned schedule times: they are never shifted to make a gap fit. Walking,
waiting and changes included by the provider remain part of the journey.

Home stops compare actual return-home arrival with the next outbound departure,
including scheduled waiting, parking allowances and minimum useful time at home.
A stop is suggested only when the required times are known and fit. Unknown event
finish times and untimed/all-day entries are flagged; use an optional finish-time
override or edit the calendar. Event order stays fixed. Plans start at home and
track planned movements, not actual GPS or proof you made a journey. Timetables
can change; check disruption information before travelling. Driving/walking
estimates from FOSSGIS do not include live traffic.

## One-time bus/train connection

Real bus/train times require timetable API access. The app automatically reuses
existing `transport_api.app_id` and `transport_api.app_key` entries in the ignored
`passwords.json`. The account must include **TAPI Journey Planner** access;
rail departure-board access alone may not include this service. No new account,
subscription or paid plan is purchased by the app.

Alternatively set these server environment variables before starting the app:

```bash
export RECEIPT_TRANSPORT_APP_ID='YOUR_APP_ID'
export RECEIPT_TRANSPORT_APP_KEY='YOUR_APP_KEY'
```

Get credentials and review your account's allowance/pricing at
[TransportAPI](https://developer.transportapi.com/). Keys are sent only in HTTPS
headers to the fixed TransportAPI host; never in browser HTML, query strings,
route cache filenames, receipts or user-facing error text. No manual journey
entry is needed once the connection is available. If it is not connected or the
provider returns no usable journey, the app says so; it does not invent bus times.
Provider results and acknowledgements are shown with the route.

The documented API is `/v3/uk/public_journey.json`, with origin/destination,
date/time and `journey_time_type=arrive_by` or `leave_after`. Up to 24 transit
lookups are considered per plan, within the shared request/deadline limits.
Timetable responses are cached for five minutes using endpoint/date/time/account
scope; credentials themselves are not stored in cache. Route access and coverage
depend on the connected account and provider. The app has not been exercised with
the owner's live account; tests use synthetic scheduled journeys.

## Overrides and privacy

Per-event travel mode, home-stop preference, finish time and exclusions remain
editable. Manual one-way duration overrides are optional and tucked under
**Advanced: override a journey duration**. Driving overrides still receive the
parking allowance. Reverse journeys have separate overrides; remove an override
to resume automatic timing. Replan after changes.

Planning sends location text to Photon/komoot, UK postcodes to Postcodes.io when
needed, confirmed coordinates to FOSSGIS and timetable endpoints to TransportAPI.
Event titles and calendar feed URLs are not sent to those providers. The street
map fetches OpenStreetMap tiles; it sends the site origin and viewed map area,
not calendar titles or page query strings. Directions and timetables are shown
in the app; no Google Maps request is needed. Provider logs cannot be deleted here.

The authenticated web app saves home, map points, manual durations and at most
31 selected-day snapshots locally in owner-only files, with CSRF and no-store
protections. Git, receipts and ordinary backups exclude these files. They are not
separately encrypted like the smart-home credential vault: protect the host and
use private HTTPS/VPN access. **Clear travel data** removes local settings, plans
and provider JSON cache once an active job has finished. External provider logs
and separate copies are unaffected.

Limits: 30 events/day, 200 places, 500 manual directional overrides, one background
planner/installation, bounded downloads/timeouts and a two-minute provider budget.
Network calls are rate-limited to at most one per second with an identifying
User-Agent. Geocoding caches last 30 days; street routes one day; timetable
responses five minutes. Private cache files are capped at 500. Public map services
are best-effort and intended for modest use. HTTPS-compatible Photon/FOSSGIS bases
can be changed by a trusted admin using `RECEIPT_TRAVEL_GEOCODER` and
`RECEIPT_TRAVEL_ROUTER`. Larger deployments should use suitable provider accounts
or self-hosted services.

Sources and terms:

- [TransportAPI documentation](https://docs.transportapi.com/)
- [Official journey API schema](https://docs.transportapi.com/openapi/paths/public_journey.yaml)
- [Photon](https://github.com/komoot/photon#demo-server)
- [UK postcode lookup](https://postcodes.io/docs/api/lookup-postcode/)
- [FOSSGIS routing privacy/usage](https://routing.openstreetmap.de/about.html)
- [OpenStreetMap tile usage](https://operations.osmfoundation.org/policies/tiles/)

Leaflet 1.9.4 is vendored locally with its BSD-2-Clause license and verified
original JS/CSS hashes. No external JavaScript CDN is used.

## At-home events and directions on the page

A calendar event with an empty location is assumed to be **at home**. Its start
and finish still reserve time, so a preceding away appointment can require a
return home, and the next journey cannot depart before the home event finishes.
Consecutive home events create no zero-minute travel cards and do not trigger a
trip merely to collect a parked car. Locationless all-day entries create no timed
journey or demand for an address; their calendar entry remains visible.

Journey cards show clearly labelled **Departure** and **Arrival** times. Street
routing requests include OSRM maneuver steps, rendered as directions with road
names, turns, roundabout exits and distances. Transit cards show an on-page
journey timetable with service numbers, stops, walking/waiting segments and
changes. Full provider timestamps retain next-day and timezone context when
available. Missing step times are labelled as not supplied, not fabricated.

There is no Google Maps button or dependency for these details. Unknown/manual
routes without provider instructions say that detailed directions are unavailable.
A bounded list of at most 200 street steps is shown, with an explicit truncation
notice for longer routes. Routing directions and times are provider estimates;
check signs, access restrictions and service disruption information while travelling.
Rebuild older saved plans to fetch the new details.
