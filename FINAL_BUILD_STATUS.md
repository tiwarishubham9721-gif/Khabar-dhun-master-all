# KHABAR DHUN V15 — BUILD STATUS

This build fixes the automatic-publication blockage found in V14.

## Fixed
- Automatic feed clusters now create `story_sources` observations.
- Non-sensitive stories from successfully fetched configured publisher feeds are automatically published to Website/App/E-paper views with source attribution.
- Sensitive/political/election/court/death/communal/national-security style stories remain HOLD for human verification.
- Automatic stories get category and local-location classification.
- Manual corroboration verification now uses a practical 2-independent-source gate instead of an impossible 8-source gate.
- No external account is marked CONNECTED without actual authorization.

## Still connection-required
YouTube, Meta, WhatsApp Business, AI/TTS/video providers, payment, physical studio/LCD/red-light hardware.

## Important
The server must have outbound internet access to fetch the configured publisher RSS feeds. If Railway blocks a feed, that source will show ERROR and retry on the next cycle; it will not be falsely marked LIVE.
