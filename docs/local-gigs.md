# Gigs today

The information receipt and authenticated **Gigs today** page show nearby music events for the receipt's date. The website can also browse another date and open event/ticket links. Searches use the saved receipt location coordinates, not device GPS. Changing location or radius changes the search. There is no fixed Birmingham venue list.

Open **Gigs today** from **Plan and review** on the home page. Obtain a Ticketmaster Discovery API key and enter it in the gig settings, or set `TICKETMASTER_API_KEY` on the server. No code edits are needed. Environment-managed keys take precedence. Keys saved through the web page are stored in ignored `data/local_gigs_config.json`, with owner-only permissions where supported. Keys are never rendered back into the page or included in request error messages. Keep this file in private backups only.

The default radius is 25 km and the receipt prints up to eight listings. Both are editable on the gig page. The receipt toggle is also in the main receipt settings. More retrieved events appear on the website. Without a key, the receipt explains where to configure listings instead of saying there are no gigs.

The provider query uses a geographic geohash, radius in kilometres, Music classification and the selected day's local midnight-to-midnight range. Returned events are checked against the exact local date and, where venue coordinates exist, the radius. Cancelled/postponed events and dates to be announced are excluded. Duplicate name/venue/time listings are collapsed. Unknown event times remain “Time TBC”; listed times may be doors times and should be confirmed with the venue.

Coverage is limited to Ticketmaster Discovery listings. Independently ticketed gigs, club nights, classical concerts classified differently, and some smaller venues may be absent. An empty successful search says no matching gigs were found **in this source**, not that no local events exist. Provider failures and incomplete/paginated results are clearly marked.

Successful results are cached in memory for 15 minutes; failures retry after about a minute. Requests have five-second timeouts and retrieve at most two pages of 200 events. Larger searches are labelled incomplete. The live preview progress tracker reports “Checking today's local gigs”. No extra dependency or Spotify artist filtering is used.

Official API reference: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
