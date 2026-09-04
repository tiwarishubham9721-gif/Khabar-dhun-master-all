# KHABAR DHUN — FINAL MASTER CONTROL 3.0

यह एक consolidated software foundation है। अलग-अलग panel/package की जरूरत न पड़े, इसी Master Control में departments, AI command registry, newsroom, verification/hold, broadcast routing, ads/payment architecture, call tickets, website route और security/audit foundation रखे गए हैं।

## सच की स्थिति
- BUILT: FastAPI app, SQLite schema, owner bootstrap via environment, PBKDF2 password hashing, JWT session, RBAC foundation, audit log, security events, news intake, sensitive hard-hold, source registry, on-demand RSS fetch foundation, clustering, 8-source verification gate, schedules, output source registry, ad order/ticket records, Master AI safe command registry, public `/site` route.
- REQUIRED / NOT VERIFIED: cloud deployment, public domain, production HTTPS/MFA/WAF, continuous 8–10 source monitoring worker, real AI provider, YouTube/Meta/WhatsApp APIs, AI anchor/video renderer/TTS, 24×7 playout/encoder, physical studio ingest, final-output LCD signal, IoT red light/buzzer, payment gateway/merchant verification, telephony/IVR, automated e-paper at 5 AM, Android apps, production website frontend/CDN, backups/object storage.

## Owner setup
Set `OWNER_USERNAME`, `OWNER_PASSWORD`, `JWT_SECRET`. For production, use strong unique secrets and a real secret manager/environment variables. Never commit secrets.

## Local run
```bash
pip install -r requirements.txt
export OWNER_PASSWORD='CHANGE_ME'
export JWT_SECRET='CHANGE_ME_LONG_RANDOM'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## FastAPI Cloud
FastAPI Cloud supports `fastapi deploy` and has a free Hobby plan, but the free plan is 0.1 vCPU/512 MB shared with scale-to-zero. इसलिए इसे अभी आसान initial deployment/test path मानें, 24×7 broadcast production guarantee नहीं।

## Safety
Sensitive/legal/political/communal/child/sexual/national-security/unconfirmed-death content is not auto-published. The verification gate is a decision aid, not proof of truth. External APIs are never marked connected without actual credentials and successful verification.
