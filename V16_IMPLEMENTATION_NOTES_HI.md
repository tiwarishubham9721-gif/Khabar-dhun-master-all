# KHABAR DHUN V16 — Live Monitoring + Separate Election Desk + Studio Output

## Implemented in this build
- Continuous configured-feed worker defaults to 60 seconds (override with FEED_INTERVAL_SECONDS).
- 12 named major-channel monitors remain registered: Aaj Tak, ABP News, India TV, News18 India, Zee News, TV9 Bharatvarsh, NDTV India, Times Now Navbharat, Republic Bharat, News24, CNBC Awaaz, DD News.
- Official/government sources and local-first architecture preserved.
- Separate Election Desk endpoint/UI; election signals are detected from monitored feed items while normal news monitoring continues.
- Separate Studio Program Output page at `/studio-output` and Control Room link.
- YouTube OAuth preparation now generates the official Google OAuth URL when GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_REDIRECT_URI are configured in Railway Variables.
- Meta OAuth preparation uses META_APP_ID and META_OAUTH_REDIRECT_URI for Facebook/Instagram/WhatsApp Business authorization preparation.
- OAuth callback records AUTHORIZED_PENDING_TEST; CONNECTED is not claimed until a real provider test succeeds.

## Important truth status
A public-monitor URL is not treated as a live feed unless a verified feed/API/authorized integration is configured. This build does not scrape or copy protected broadcasts.
Physical studio, LCD, encoder, red-light and siren still require the actual Studio Gateway/hardware and a successful health check.
