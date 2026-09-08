# Android Apps

The Android folder contains two separate applications:

1. `public-app` — public KHABAR DHUN Android application.
2. `owner-control` — secure Owner Master Control Room application.

They use the same central backend architecture but have separate Android application IDs and entry points.

Before building, replace `https://YOUR-RAILWAY-DOMAIN` in each app's `strings.xml` with the verified production HTTPS backend URL.

These are real Android application projects, not a Chrome Add-to-Home-Screen shortcut. Final signed APK/AAB generation still requires an Android build environment and the Owner's signing credentials.
