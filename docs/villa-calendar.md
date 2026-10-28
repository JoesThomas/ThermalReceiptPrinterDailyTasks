# Villa fixtures in the receipt and app calendar

With **Calendar** and **Villa match information** enabled, the daily receipt and
Calendar events page automatically combine personal iCal events with Aston Villa
men's first-team fixtures. Home, away, league and cup games are included. Fixture
dates use Europe/London, including British Summer Time.

The club's public fixtures page is the primary source; no football API key is
required. The parser reads fixture data from the page's embedded JSON without
executing JavaScript. The existing football-data.org key is an optional fallback.
Fallback coverage is explicitly labelled as potentially incomplete. The club
source uses the shared private cache (15-minute normal refresh, at most six-hour
fallback) and bounded network/download limits. Missing data is reported rather
than interpreted as confirmation that Villa are not playing.

An existing personal event takes precedence when its date and team names identify
the same match, even if its UID, punctuation, kick-off label or AFC/FC spelling
varies. Common Villa/AVFC match labels are also recognized. Your saved title,
location and time remain intact. Travel, ticket, women's-team and youth-team
entries are kept separate. Different opponents or match dates are not merged.
Repeated auto-fixture IDs are inserted only once.

The receipt prints the match in TODAY'S CALENDAR rather than repeating it in a
separate MATCH DAY block. Bournville-to-Aston train information remains available
for home matches when enabled; away matches do not trigger those trains. If the
Calendar receipt feature is disabled, the standalone Villa match block remains
available for home and away fixtures.

The Calendar events page refreshes the shared local snapshot used on Home. Merely
opening Home continues to use saved data without fetching external services.
Villa fixtures can still appear when the personal calendar is unavailable, and
personal events can still appear if the fixture source fails. Warnings are shown
for the missing source. Local map/location overrides continue to apply.

This combines events locally for the receipt and web app. It does not create,
change or subscribe to events in Google Calendar.
