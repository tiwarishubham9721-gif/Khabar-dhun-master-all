# KHABAR DHUN V15 — REAL AUTO NEWS FIX

V14 में automatic feed आने के बाद भी public website खाली रहने का मुख्य कारण यह था कि auto-ingested stories को `story_sources` में attach नहीं किया जा रहा था और verification gate 8 independent sources मांग रहा था। इस build में वह blockage ठीक किया गया है।

अब configured publisher RSS feed successfully fetch होने पर non-sensitive source-backed story automatically Website/App/E-paper news list में आ सकती है। Sensitive stories human HOLD में रहेंगी।

Railway deployment में outbound internet आवश्यक है। Feed failure होने पर source ERROR/last-check दिखेगा और अगली cycle में retry होगा।

External publishing accounts और physical studio hardware अलग connection steps हैं और उन्हें fake LIVE नहीं किया जाएगा।
