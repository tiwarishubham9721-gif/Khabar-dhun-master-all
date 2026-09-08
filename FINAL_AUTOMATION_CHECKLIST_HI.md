# KHABAR DHUN — FINAL AUTOMATION CHECKLIST

## इस पैकेज में सक्रिय
- Master AI Command Center का safe command engine
- Automatic feed worker (default 5 मिनट)
- Story clustering / duplicate grouping
- Sensitive story HOLD gate
- News + photo/video/audio upload
- Public news website + article pages
- Public customer advertisement page
- Public App/PWA page
- Live App QR: website, ad page, e-paper, broadcast overlay
- IST clock endpoint and visible clock on public/control pages
- Self Promotion / Publicity department
- App promotion rotation
- Festival Greetings automation and scheduled festival messages
- Master Output orchestration mode / output event logging
- Audit and security event logging

## Festival automation
The 2026 seed includes major dates such as Holi, Independence Day, Raksha Bandhan, Janmashtami, Ganesh Chaturthi, Dussehra, Diwali and Chhath. The engine prepares greeting records ahead of the date and exposes the next 7-day greeting on the public site.

## जरूरी वास्तविक बाहरी कनेक्शन
यह software अपने-आप API keys/merchant accounts/YouTube OAuth नहीं बना सकता। Production में निम्न credentials/connections देना जरूरी है:
- AI provider API
- Voice/TTS provider
- AI anchor/avatar provider
- Video renderer/encoder
- YouTube OAuth/API
- Meta/Facebook/Instagram API
- WhatsApp Business API
- Payment gateway merchant/API + webhook
- Email/SMS/telephony
- Persistent Railway Volume or object storage for `/data`

इन credentials के बिना संबंधित modules को fake-connected दिखाना जानबूझकर नहीं किया गया है।

## Railway persistence
SQLite database और uploaded media `/data` में हैं। Railway पर `/data` का persistent Volume लगाना आवश्यक है, वरना redeploy/restart पर data/media खो सकते हैं।

## App
अभी App installable PWA है (`/app`), native Play Store APK/AAB नहीं। Play Store publishing के लिए अलग Android build और developer account process चाहिए।
