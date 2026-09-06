import os, re, sqlite3, json, hashlib, secrets, urllib.request, xml.etree.ElementTree as ET, asyncio, threading, time, uuid, mimetypes
from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import qrcode

DB=os.getenv('DATABASE_URL','sqlite:////data/khabar_dhun.db').replace('sqlite:///','') or '/data/khabar_dhun.db'
if not DB.startswith('/'): DB='/data/khabar_dhun.db'
SECRET=os.getenv('JWT_SECRET','CHANGE_ME_IN_PRODUCTION')
OWNER=os.getenv('OWNER_USERNAME','owner')
OWNER_PASSWORD=os.getenv('OWNER_PASSWORD','')
templates=Jinja2Templates(directory='app/templates')
MEDIA_DIR=Path(os.getenv('MEDIA_DIR','/data/media'))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app=FastAPI(title='KHABAR DHUN — FINAL MASTER CONTROL', version='3.0.0')
NOW=lambda: datetime.now(timezone.utc).isoformat()
MAX_MEDIA_MB=int(os.getenv('MAX_MEDIA_MB','100'))
AUTO_FEED_ENABLED=os.getenv('AUTO_FEED_ENABLED','1')=='1'
FEED_INTERVAL=int(os.getenv('FEED_INTERVAL_SECONDS','300'))

ROLES={'OWNER','EDITOR','NEWS_DESK','VIDEO_DESK','SOCIAL_DESK','EPAPER_DESK','AD_DESK','BACKUP_MANAGER'}
SENSITIVE=re.compile(r'allegation|आरोप|मौत|मृत्यु|communal|सांप्रदायिक|religious|धर्म|election|चुनाव|sexual|यौन|child|बच्चा|court|अदालत|war|युद्ध|national security|राष्ट्रीय सुरक्षा',re.I)

def db():
    os.makedirs(os.path.dirname(DB) or '.',exist_ok=True); c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def hash_password(p):
    salt=secrets.token_bytes(16); h=hashlib.pbkdf2_hmac('sha256',p.encode(),salt,310000); return 'pbkdf2$310000$'+salt.hex()+'$'+h.hex()
def verify_password(p,s):
    try:
        scheme,it,salt,raw=s.split('$',3); return scheme=='pbkdf2' and secrets.compare_digest(hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),int(it)).hex(),raw)
    except Exception: return False

def init():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT, enabled INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS brand(id INTEGER PRIMARY KEY CHECK(id=1), name TEXT, short_name TEXT, tagline TEXT, station_id TEXT, logo_path TEXT, primary_color TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY, name TEXT UNIQUE, category TEXT, enabled INTEGER DEFAULT 1, created_by TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY, name TEXT UNIQUE, kind TEXT, status TEXT DEFAULT 'NOT_CONNECTED', enabled INTEGER DEFAULT 1, config_json TEXT DEFAULT '{}', created_at TEXT);
    CREATE TABLE IF NOT EXISTS anchors(id INTEGER PRIMARY KEY, name TEXT UNIQUE, voice_id TEXT, avatar_id TEXT, studio_id TEXT, status TEXT DEFAULT 'NOT_CONFIGURED', active INTEGER DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY, title TEXT, body TEXT, category TEXT, location TEXT, source TEXT, risk TEXT DEFAULT 'NORMAL', confidence REAL DEFAULT 0, status TEXT DEFAULT 'DRAFT', created_at TEXT, approved_by TEXT);
    CREATE TABLE IF NOT EXISTS hold_queue(id INTEGER PRIMARY KEY, news_id INTEGER, reason TEXT, confidence REAL, risk TEXT, source_comparison TEXT, status TEXT DEFAULT 'HOLD', created_at TEXT, resolved_by TEXT);
    CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, name TEXT UNIQUE, url TEXT, enabled INTEGER DEFAULT 1, status TEXT DEFAULT 'NOT_CONNECTED');
    CREATE TABLE IF NOT EXISTS story_sources(id INTEGER PRIMARY KEY, news_id INTEGER, source_id INTEGER, headline TEXT, url TEXT, observed_at TEXT, independent_group TEXT, verified INTEGER DEFAULT 0, notes TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS verification_runs(id INTEGER PRIMARY KEY, news_id INTEGER, independent_sources INTEGER DEFAULT 0, total_sources INTEGER DEFAULT 0, confidence REAL DEFAULT 0, conflict INTEGER DEFAULT 0, decision TEXT DEFAULT 'HOLD', reasons TEXT DEFAULT '', created_at TEXT);
    CREATE TABLE IF NOT EXISTS feed_items(id INTEGER PRIMARY KEY, source_id INTEGER, guid TEXT UNIQUE, title TEXT, summary TEXT, url TEXT, published_at TEXT, fetched_at TEXT, cluster_key TEXT, status TEXT DEFAULT 'INGESTED');
    CREATE TABLE IF NOT EXISTS story_clusters(id INTEGER PRIMARY KEY, cluster_key TEXT UNIQUE, title TEXT, item_count INTEGER DEFAULT 0, source_count INTEGER DEFAULT 0, confidence REAL DEFAULT 0, status TEXT DEFAULT 'CANDIDATE', updated_at TEXT);
    CREATE TABLE IF NOT EXISTS schedules(id INTEGER PRIMARY KEY, title TEXT, start_at TEXT, end_at TEXT, kind TEXT, status TEXT DEFAULT 'SCHEDULED', created_at TEXT);
    CREATE TABLE IF NOT EXISTS onair(id INTEGER PRIMARY KEY CHECK(id=1), source TEXT, mode TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS ads(id INTEGER PRIMARY KEY, campaign TEXT, mode TEXT, start_at TEXT, end_at TEXT, status TEXT DEFAULT 'DRAFT', price REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS ad_orders(id INTEGER PRIMARY KEY, advertiser TEXT, package TEXT, amount REAL, payment_status TEXT DEFAULT 'PENDING', campaign_status TEXT DEFAULT 'DRAFT', created_at TEXT, contact_name TEXT, phone TEXT, email TEXT, city TEXT, creative TEXT);
    CREATE TABLE IF NOT EXISTS call_tickets(id INTEGER PRIMARY KEY, channel TEXT, caller TEXT, category TEXT, message TEXT, status TEXT DEFAULT 'NEW', created_at TEXT);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor TEXT, action TEXT, details TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS commands(id INTEGER PRIMARY KEY, command TEXT, intent TEXT, status TEXT, result TEXT, actor TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS security_events(id INTEGER PRIMARY KEY, severity TEXT, event_type TEXT, actor TEXT, details TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS security_settings(id INTEGER PRIMARY KEY CHECK(id=1), lockdown INTEGER DEFAULT 0, updated_at TEXT, updated_by TEXT);
    CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, path TEXT, rights_status TEXT DEFAULT 'UNKNOWN', enabled INTEGER DEFAULT 1, created_at TEXT);
    CREATE TABLE IF NOT EXISTS epaper(id INTEGER PRIMARY KEY, edition_date TEXT UNIQUE, status TEXT DEFAULT 'DRAFT', file_path TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS reporters(id INTEGER PRIMARY KEY, username TEXT UNIQUE, district TEXT, verification_status TEXT DEFAULT 'PENDING', created_at TEXT);
    CREATE TABLE IF NOT EXISTS integrations(id INTEGER PRIMARY KEY, name TEXT UNIQUE, status TEXT DEFAULT 'NOT_CONNECTED', notes TEXT);
    CREATE TABLE IF NOT EXISTS output_events(id INTEGER PRIMARY KEY, event_type TEXT, payload TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS festival_promotions(id INTEGER PRIMARY KEY, festival_name TEXT, festival_date TEXT, message TEXT, status TEXT DEFAULT 'SCHEDULED', channels TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS promo_rotation(id INTEGER PRIMARY KEY, title TEXT, message TEXT, kind TEXT, active INTEGER DEFAULT 1, priority INTEGER DEFAULT 50, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS system_settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS news_media(id INTEGER PRIMARY KEY, news_id INTEGER, original_name TEXT, stored_name TEXT, mime_type TEXT, size INTEGER, path TEXT, created_at TEXT, uploaded_by TEXT);
    CREATE INDEX IF NOT EXISTS idx_feed_cluster ON feed_items(cluster_key);
    CREATE INDEX IF NOT EXISTS idx_news_status ON news(status);
    ''')
    if not c.execute('SELECT id FROM brand WHERE id=1').fetchone(): c.execute('INSERT INTO brand VALUES(1,?,?,?,?,?,?,?)',('KHABAR DHUN','KD','Lagatar chalte khabron ka dhun','KHABAR DHUN','/static/logo.svg','#18a0ff',NOW()))
    if not c.execute('SELECT id FROM onair WHERE id=1').fetchone(): c.execute('INSERT INTO onair VALUES(1,"DIGITAL_BACKUP","NORMAL",?)',(NOW(),))
    if not c.execute('SELECT id FROM security_settings WHERE id=1').fetchone(): c.execute('INSERT INTO security_settings VALUES(1,0,?,?)',(NOW(),'SYSTEM'))
    deps=['News Research','Verification','Breaking News','News Desk','Script Writer','Video Production','Graphics','AI Anchor','Shooting / Camera','Music','Programming / Master Control','Video QC','Social Media','WhatsApp','E-paper','Advertisement','Comments','Analytics','Backup / Operations','Weather','Agriculture / Farmers','Health','Education','Science / Technology','Law / Court','Crime / Investigation','Political Analysis','Elections','Business / Economy','Sports','Entertainment / Cinema / OTT','Auto / Travel','Lifestyle','Human Interest','Fact Check','Ground / Local Reporter','Interviews / Dialogue','Debate / Analysis','Special Coverage','Disaster / Emergency','Photo / Video','Live Reporting','Audience / Comments','Podcast / Audio','International','Self Promotion / Publicity','Festival Greetings','Audience Growth / App Promotion']
    for n in deps: c.execute('INSERT OR IGNORE INTO departments(name,category,created_by,created_at) VALUES(?,?,?,?)',(n,'NEWSROOM','SYSTEM',NOW()))
    for n in ['YouTube','Facebook','Instagram','WhatsApp Business','AI Provider','Video Renderer','Voice / TTS','Payment Gateway','Email','SMS / Calling','Cloud / Object Storage','IoT Studio Red Light + Buzzer']: c.execute('INSERT OR IGNORE INTO services(name,kind) VALUES(?,?)',(n,'EXTERNAL'))
    sources=[('Press Information Bureau','https://pib.gov.in/'),('Election Commission of India','https://www.eci.gov.in/'),('India Meteorological Department','https://mausam.imd.gov.in/'),('Reuters','https://www.reuters.com/'),('The Hindu','https://www.thehindu.com/'),('Indian Express','https://indianexpress.com/'),('Hindustan Times','https://www.hindustantimes.com/'),('NDTV','https://www.ndtv.com/'),('BBC News','https://www.bbc.com/news'),('ANI','https://www.aninews.in/')]
    for n,u in sources: c.execute('INSERT OR IGNORE INTO sources(name,url,status) VALUES(?,?,?)',(n,u,'NOT_CONNECTED'))
    for n in ['YouTube','Facebook','Instagram','WhatsApp Business']: c.execute('INSERT OR IGNORE INTO integrations(name) VALUES(?)',(n,))
    for n in ['Anchor 1','Anchor 2','Anchor 3']: c.execute('INSERT OR IGNORE INTO anchors(name,created_at) VALUES(?,?)',(n,NOW()))
    # Safe migrations for existing databases
    try: c.execute('ALTER TABLE news ADD COLUMN cluster_key TEXT')
    except Exception: pass
    for col,typ in [('contact_name','TEXT'),('phone','TEXT'),('email','TEXT'),('city','TEXT'),('creative','TEXT')]:
        try: c.execute(f'ALTER TABLE ad_orders ADD COLUMN {col} {typ}')
        except Exception: pass
    c.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES('public_ad_url','/ad')")
    c.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES('public_app_url','/app')")
    c.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES('time_zone','Asia/Kolkata')")
    c.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES('auto_festival_greetings','1')")
    c.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES('self_promotion_enabled','1')")
    c.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES('app_qr_enabled','1')")
    c.commit(); c.close()
init()

def audit(actor,action,details=''):
    c=db(); c.execute('INSERT INTO audit(actor,action,details,created_at) VALUES(?,?,?,?)',(actor,action,details,NOW())); c.commit(); c.close()
def log_security(actor,event,details='',severity='INFO'):
    c=db(); c.execute('INSERT INTO security_events(severity,event_type,actor,details,created_at) VALUES(?,?,?,?,?)',(severity,event,actor,details,NOW())); c.commit(); c.close()
def token(u):
    exp=int((datetime.now(timezone.utc)+timedelta(hours=12)).timestamp())
    payload=f"{u}|{exp}"
    sig=hashlib.sha256((payload+SECRET).encode()).hexdigest()
    return payload+'|'+sig
def decode_token(t):
    parts=(t or '').split('|')
    if len(parts)!=3: raise ValueError('bad token')
    u,exp,sig=parts
    if int(exp)<int(datetime.now(timezone.utc).timestamp()): raise ValueError('expired')
    expected=hashlib.sha256((u+'|'+exp+SECRET).encode()).hexdigest()
    if not secrets.compare_digest(sig,expected): raise ValueError('bad signature')
    return u
def current_user(request:Request):
    t=request.cookies.get('kd_session')
    if not t: return None
    try:
        u=decode_token(t); c=db(); r=c.execute('SELECT * FROM users WHERE username=? AND enabled=1',(u,)).fetchone(); c.close(); return dict(r) if r else None
    except Exception: return None
def require_user(request:Request):
    u=current_user(request)
    if not u: raise HTTPException(401,'Authentication required')
    return u
def owner_only(u):
    if u['role']!='OWNER': raise HTTPException(403,'Owner only')

def bootstrap_owner():
    if not OWNER_PASSWORD:
        return
    c = db()
    row = c.execute('SELECT id, password_hash FROM users WHERE username=?', (OWNER,)).fetchone()
    new_hash = hash_password(OWNER_PASSWORD)
    if not row:
        c.execute(
            'INSERT INTO users(username,password_hash,role,enabled) VALUES(?,?,?,1)',
            (OWNER, new_hash, 'OWNER')
        )
    elif not verify_password(OWNER_PASSWORD, row['password_hash']):
        c.execute(
            'UPDATE users SET password_hash=?, role=?, enabled=1 WHERE username=?',
            (new_hash, 'OWNER', OWNER)
        )
    c.commit()
    c.close()

bootstrap_owner()
app.mount('/media', StaticFiles(directory=str(MEDIA_DIR)), name='media')


def words(text): return set(re.findall(r'[A-Za-z0-9अ-ह]{3,}',(text or '').lower()))
def cluster_key(title): return hashlib.sha1(' '.join(sorted(words(title))).encode()).hexdigest()[:16]

DEFAULT_FEEDS={
 'Press Information Bureau':'https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3',
 'The Hindu':'https://www.thehindu.com/feeder/default.rss',
 'Indian Express':'https://indianexpress.com/feed/',
 'Hindustan Times':'https://www.hindustantimes.com/feeds/rss',
 'NDTV':'https://feeds.feedburner.com/ndtvnews-top-stories',
 'BBC News':'https://feeds.bbci.co.uk/news/rss.xml',
 'ANI':'https://aninews.in/rss'
}

def ensure_feed_urls():
    c=db()
    for name,url in DEFAULT_FEEDS.items():
        c.execute('UPDATE sources SET url=? WHERE name=? AND (url IS NULL OR url="" OR url LIKE ?)',(url,name,'%'+name.lower().replace(' ','')+'%'))
    c.commit(); c.close()

def fetch_rss_source(source_id,timeout=12):
    c=db(); src=c.execute('SELECT * FROM sources WHERE id=?',(source_id,)).fetchone()
    if not src: c.close(); return {'error':'source not found'}
    url=src['url'] or ''
    if not url.startswith(('http://','https://')): c.close(); return {'error':'feed URL not configured'}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'KHABAR-DHUN-NewsEngine/3.0'})
        data=urllib.request.urlopen(req,timeout=timeout).read(); root=ET.fromstring(data); items=[]
        for item in root.findall('.//item')[:100]:
            title=(item.findtext('title') or '').strip(); link=(item.findtext('link') or '').strip(); guid=(item.findtext('guid') or link or title).strip(); summary=(item.findtext('description') or '').strip(); pub=(item.findtext('pubDate') or '').strip()
            if not title: continue
            ck=cluster_key(title); c.execute('INSERT OR IGNORE INTO feed_items(source_id,guid,title,summary,url,published_at,fetched_at,cluster_key) VALUES(?,?,?,?,?,?,?,?)',(source_id,guid,title,summary,link,pub,NOW(),ck)); items.append({'title':title,'url':link,'cluster_key':ck})
        c.execute('UPDATE sources SET status=? WHERE id=?',('FETCHED',source_id)); c.commit(); c.close(); return {'source':src['name'],'items':len(items),'items_preview':items[:10]}
    except Exception as e: c.close(); return {'source':src['name'],'error':str(e),'note':'Network fetch is on-demand; continuous monitoring is not claimed.'}

def rebuild_clusters():
    c=db(); groups={}
    for r in c.execute('SELECT cluster_key, title, source_id FROM feed_items ORDER BY fetched_at DESC LIMIT 2000').fetchall(): groups.setdefault(r['cluster_key'],[]).append(r)
    out=[]
    for k,rows in groups.items():
        title=rows[0]['title']; sc=len(set(x['source_id'] for x in rows)); conf=min(.99,sc/8); c.execute('INSERT INTO story_clusters(cluster_key,title,item_count,source_count,confidence,status,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(cluster_key) DO UPDATE SET title=excluded.title,item_count=excluded.item_count,source_count=excluded.source_count,confidence=excluded.confidence,updated_at=excluded.updated_at',(k,title,len(rows),sc,conf,'CANDIDATE',NOW())); out.append({'cluster_key':k,'title':title,'item_count':len(rows),'source_count':sc,'confidence':conf})
    c.commit(); c.close(); return out

def auto_promote_feed_clusters():
    c=db(); created=0
    rows=c.execute('SELECT cluster_key,title,item_count,source_count,confidence FROM story_clusters WHERE item_count>0 ORDER BY updated_at DESC LIMIT 200').fetchall()
    for cl in rows:
        if c.execute('SELECT id FROM news WHERE cluster_key=?',(cl['cluster_key'],)).fetchone(): continue
        item=c.execute('SELECT summary,url,source_id FROM feed_items WHERE cluster_key=? ORDER BY fetched_at DESC LIMIT 1',(cl['cluster_key'],)).fetchone()
        if not item: continue
        srcs=c.execute('SELECT name FROM sources WHERE id IN (SELECT DISTINCT source_id FROM feed_items WHERE cluster_key=?)',(cl['cluster_key'],)).fetchall()
        source_text=', '.join(x['name'] for x in srcs[:12])
        risk='SENSITIVE' if SENSITIVE.search(cl['title'] or '') else 'NORMAL'
        status='HOLD' if risk=='SENSITIVE' else 'DRAFT'
        cur=c.execute('INSERT INTO news(title,body,category,location,source,risk,confidence,status,created_at,cluster_key) VALUES(?,?,?,?,?,?,?,?,?,?)',(cl['title'],(item['summary'] or 'Automatic feed intake; full article at source URL.')[:12000],'AUTO', '', source_text, risk, cl['confidence'], status, NOW(), cl['cluster_key']))
        nid=cur.lastrowid
        if risk=='SENSITIVE': c.execute('INSERT INTO hold_queue(news_id,reason,confidence,risk,source_comparison,created_at) VALUES(?,?,?,?,?,?)',(nid,'Automatic sensitive-news hold',cl['confidence'],risk,source_text,NOW()))
        created+=1
    c.commit(); c.close(); return created

def automatic_feed_cycle():
    set_automation_heartbeat('feed_worker')
    ensure_feed_urls()
    c=db(); ids=[r['id'] for r in c.execute('SELECT id FROM sources WHERE enabled=1').fetchall()]; c.close()
    for sid in ids:
        try: fetch_rss_source(sid,timeout=10)
        except Exception: pass
    rebuild_clusters(); return auto_promote_feed_clusters()

def feed_worker():
    # Single-process Railway worker; external integrations remain optional.
    while True:
        try:
            if AUTO_FEED_ENABLED: automatic_feed_cycle()
        except Exception: pass
        time.sleep(max(60,FEED_INTERVAL))

def start_feed_worker():
    if not AUTO_FEED_ENABLED: return
    t=threading.Thread(target=feed_worker,name='khabar-dhun-feed-worker',daemon=True); t.start()

start_feed_worker()

def verification_for_news(nid):
    c=db(); n=c.execute('SELECT * FROM news WHERE id=?',(nid,)).fetchone(); rows=c.execute('SELECT ss.*,s.name FROM story_sources ss JOIN sources s ON s.id=ss.source_id WHERE ss.news_id=?',(nid,)).fetchall(); c.close()
    if not n: raise HTTPException(404,'News not found')
    groups={r['independent_group'] or r['name'] for r in rows}; verified=[r for r in rows if r['verified']]; reasons=[]
    if n['risk']=='SENSITIVE' or SENSITIVE.search((n['title'] or '')+' '+(n['body'] or '')): reasons.append('Sensitive story')
    if len(groups)<8: reasons.append('Fewer than 8 independent sources')
    if len(verified)<8: reasons.append('Fewer than 8 verified observations')
    decision='AUTO_ELIGIBLE' if not reasons else 'HOLD'; return {'news_id':nid,'independent_sources':len(groups),'total_sources':len(rows),'verified_observations':len(verified),'confidence':min(.99,len(groups)/8),'decision':decision,'reasons':reasons}

# ---------- Master automation: clock, self-promotion, festival greetings ----------
FESTIVAL_RULES = [
    ("New Year","01-01"),("Republic Day","01-26"),("Maha Shivaratri","02-15"),
    ("Holi","03-04"),("Rama Navami","03-26"),("Mahavir Jayanti","03-31"),
    ("Buddha Purnima","05-01"),("Rath Yatra","07-16"),("Independence Day","08-15"),
    ("Raksha Bandhan","08-28"),("Janmashtami","09-04"),("Ganesh Chaturthi","09-14"),
    ("Gandhi Jayanti","10-02"),("Dussehra","10-20"),("Diwali","11-08"),
    ("Chhath Puja","11-15"),("Guru Nanak Jayanti","11-24"),("Christmas","12-25"),
    ("World Environment Day","06-05"),("International Women’s Day","03-08"),("Children’s Day","11-14"),
]

def public_base_url(request:Request):
    env=os.getenv('PUBLIC_BASE_URL','').rstrip('/')
    if env: return env
    return str(request.base_url).rstrip('/')

def qr_png(data:str):
    img=qrcode.make(data); bio=BytesIO(); img.save(bio,format='PNG'); bio.seek(0); return bio

def seed_self_promotion():
    c=db()
    rows=[
      ('App Promotion','KHABAR DHUN App डाउनलोड करें — QR scan करके मोबाइल में इंस्टॉल करें।','APP_PROMO',100),
      ('Publicity','KHABAR DHUN — खबर, विज्ञापन और लाइव अपडेट के लिए हमारे साथ जुड़ें।','SELF_PROMO',90),
      ('Advertise','अपने कारोबार का विज्ञापन KHABAR DHUN पर दें।','AD_PROMO',80),
    ]
    for r in rows: c.execute('INSERT OR IGNORE INTO promo_rotation(title,message,kind,priority) VALUES(?,?,?,?)',r)
    c.commit(); c.close()

def seed_festival_promotions(year:int):
    c=db()
    for name,md in FESTIVAL_RULES:
        d=f'{year}-{md}'
        msg=f'KHABAR DHUN की ओर से {name} की हार्दिक शुभकामनाएँ। सत्य, सद्भाव और सुरक्षित समाज के साथ जुड़े रहें।'
        c.execute('INSERT OR IGNORE INTO festival_promotions(festival_name,festival_date,message,channels,created_at) VALUES(?,?,?,?,?)',(name,d,msg,'WEBSITE,YOUTUBE,EPAPER,SOCIAL,WHATSAPP,APP',NOW()))
    c.commit(); c.close()

def ist_now():
    return datetime.now(timezone(timedelta(hours=5,minutes=30)))

def set_automation_heartbeat(name='master_automation'):
    try:
        c=db(); c.execute("INSERT INTO system_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(f'{name}_heartbeat',NOW())); c.commit(); c.close()
    except Exception: pass

def automation_cycle():
    try:
        set_automation_heartbeat('master_automation')
        seed_self_promotion(); seed_festival_promotions(ist_now().year)
    except Exception: pass

def start_master_automation():
    automation_cycle()
    def loop():
        while True:
            time.sleep(900)
            automation_cycle()
    t=threading.Thread(target=loop,name='khabar-dhun-master-automation',daemon=True); t.start()

start_master_automation()

def command_engine(raw,user):
    s=(raw or '').strip(); low=s.lower(); intent='UNKNOWN'; status='BUILT'; result={}
    c=db()
    if re.search(r'(system|सिस्टम).*(health|status|स्थिति)',low):
        intent='SYSTEM_HEALTH'; result={'database':'OK','master_control':'AVAILABLE','master_automation':'RUNNING','clock':'Asia/Kolkata','external_connections':'CREDENTIALS_REQUIRED'}
    elif re.search(r'(festival|त्योहार|शुभकामना)',low):
        intent='FESTIVAL_GREETING'; automation_cycle(); result={'status':'SCHEDULED','channels':'WEBSITE,YOUTUBE,EPAPER,SOCIAL,WHATSAPP,APP'}
    elif re.search(r'(promotion|प्रचार|publicity|प्रसार).*(self|अपना|khabar dhun)',low):
        intent='SELF_PROMOTION'; seed_self_promotion(); result={'status':'ACTIVE','rotation':'APP_PROMO,SELF_PROMO,AD_PROMO'}
    elif re.search(r'(time|समय|घड़ी|ghadi)',low):
        intent='CLOCK'; result={'timezone':'Asia/Kolkata','utc':NOW()}
    elif re.search(r'(output|आउटपुट).*(start|on|चालू|activate)',low):
        intent='MASTER_OUTPUT'; c.execute('UPDATE onair SET mode="AUTO",updated_at=? WHERE id=1',(NOW(),)); c.execute('INSERT INTO output_events(event_type,payload,created_at) VALUES(?,?,?)',('MASTER_OUTPUT_AUTO','ENABLED',NOW())); result={'status':'AUTO_ENABLED','note':'Physical encoder/API still requires external connection'}
    elif re.search(r'(weather|मौसम).*(department|विभाग).*(add|जोड़|जोड़)',low):
        intent='ADD_DEPARTMENT'; c.execute('INSERT OR IGNORE INTO departments(name,category,created_by,created_at) VALUES(?,?,?,?)',('Weather','NEWSROOM',user['username'],NOW())); result={'department':'Weather','status':'ENABLED'}
    elif re.search(r'(anchor|एंकर).*(add|जोड़|जोड़)',low):
        intent='ADD_ANCHOR'; name='Anchor '+str(c.execute('SELECT COALESCE(MAX(id),0)+1 FROM anchors').fetchone()[0]); c.execute('INSERT OR IGNORE INTO anchors(name,created_at) VALUES(?,?)',(name,NOW())); result={'anchor':name,'status':'CREATED','provider':'REQUIRED'}
    elif re.search(r'(service|सेवा).*(add|जोड़|जोड़)',low):
        intent='ADD_SERVICE'; result={'status':'BUILT','note':'External service credentials must be configured'}
    elif re.search(r'(lockdown|सुरक्षा बंद|security lockdown)',low):
        intent='SECURITY_LOCKDOWN'; c.execute('UPDATE security_settings SET lockdown=1,updated_at=?,updated_by=? WHERE id=1',(NOW(),user['username'])); result={'lockdown':True}
    else:
        status='LIMITED'; result={'message':'Command understood only for registered safe actions. Arbitrary code execution disabled.'}
    c.execute('INSERT INTO commands(command,intent,status,result,actor,created_at) VALUES(?,?,?,?,?,?)',(s,intent,status,json.dumps(result,ensure_ascii=False),user['username'],NOW())); c.commit(); c.close(); audit(user['username'],'MASTER_AI_COMMAND',f'{intent}:{status}'); return {'command':s,'intent':intent,'status':status,'result':result}

@app.get('/login', response_class=HTMLResponse)
def login_page(request:Request): return templates.TemplateResponse(request=request, name='login.html', context={})
@app.post('/login')
def login(username:str=Form(...),password:str=Form(...),request:Request=None):
    c=db(); r=c.execute('SELECT * FROM users WHERE username=? AND enabled=1',(username,)).fetchone(); ok=bool(r and verify_password(password,r['password_hash'])); c.close()
    if not ok: log_security(username,'LOGIN_FAILED','invalid credentials','WARN'); raise HTTPException(401,'Invalid login')
    resp=RedirectResponse('/',303); resp.set_cookie('kd_session',token(username),httponly=True,samesite='lax',secure=os.getenv('COOKIE_SECURE','0')=='1'); audit(username,'LOGIN','success'); return resp
@app.get('/logout')
def logout(): r=RedirectResponse('/login',303); r.delete_cookie('kd_session'); return r
@app.get('/',response_class=HTMLResponse)
def home(request:Request,user=Depends(require_user)): return templates.TemplateResponse(request=request, name='control.html', context={'user':user})
@app.post('/ai/command')
def ai_command(command:str=Form(...),user=Depends(require_user)): return JSONResponse(command_engine(command,user))
@app.post('/sources/add')
def source_add(name:str=Form(...),url:str=Form(''),user=Depends(require_user)):
    owner_only(user); c=db(); c.execute('INSERT OR IGNORE INTO sources(name,url,status) VALUES(?,?,?)',(name.strip(),url.strip(),'NOT_CONNECTED')); c.commit(); c.close(); audit(user['username'],'SOURCE_REGISTRY_ADD',name.strip()); return RedirectResponse('/',303)
@app.post('/news/add')
def news_add(title:str=Form(...),body:str=Form(...),category:str=Form(...),location:str=Form(''),source:str=Form(''),user=Depends(require_user)):
    risk='SENSITIVE' if SENSITIVE.search(title+' '+body) else 'NORMAL'; status='HOLD' if risk=='SENSITIVE' else 'DRAFT'; c=db(); cur=c.execute('INSERT INTO news(title,body,category,location,source,risk,status,created_at) VALUES(?,?,?,?,?,?,?,?)',(title,body,category,location,source,risk,status,NOW())); nid=cur.lastrowid
    if risk=='SENSITIVE': c.execute('INSERT INTO hold_queue(news_id,reason,confidence,risk,source_comparison,created_at) VALUES(?,?,?,?,?,?)',(nid,'Sensitive-news hard rule',0,risk,'Not yet verified',NOW()))
    c.commit(); c.close(); audit(user['username'],'NEWS_INTAKE',str(nid)); return RedirectResponse('/',303)
@app.post('/news/{news_id}/media')
async def news_media_upload(news_id:int, media:UploadFile=File(...), user=Depends(require_user)):
    c=db(); exists=c.execute('SELECT id FROM news WHERE id=?',(news_id,)).fetchone(); c.close()
    if not exists: raise HTTPException(404,'News not found')
    content=await media.read()
    if len(content)>MAX_MEDIA_MB*1024*1024: raise HTTPException(413,f'Media too large; max {MAX_MEDIA_MB} MB')
    mime=media.content_type or mimetypes.guess_type(media.filename or '')[0] or 'application/octet-stream'
    allowed_prefix=('image/','video/','audio/')
    if not mime.startswith(allowed_prefix): raise HTTPException(400,'Only image, video or audio files are allowed')
    safe_ext=Path(media.filename or '').suffix.lower()[:10]
    stored=f'{news_id}_{uuid.uuid4().hex}{safe_ext}'
    dest=MEDIA_DIR/stored; dest.write_bytes(content)
    c=db(); c.execute('INSERT INTO news_media(news_id,original_name,stored_name,mime_type,size,path,created_at,uploaded_by) VALUES(?,?,?,?,?,?,?,?)',(news_id,media.filename or stored,stored,mime,len(content),str(dest),NOW(),user['username'])); c.commit(); c.close()
    audit(user['username'],'NEWS_MEDIA_UPLOAD',f'news={news_id};file={media.filename};bytes={len(content)}')
    return RedirectResponse('/',303)

@app.post('/news/{news_id}/source')
def attach_source(news_id:int,source_id:int=Form(...),headline:str=Form(''),url:str=Form(''),independent_group:str=Form(''),verified:int=Form(0),notes:str=Form(''),user=Depends(require_user)):
    c=db();
    if not c.execute('SELECT id FROM news WHERE id=?',(news_id,)).fetchone(): c.close(); raise HTTPException(404,'News not found')
    c.execute('INSERT INTO story_sources(news_id,source_id,headline,url,observed_at,independent_group,verified,notes) VALUES(?,?,?,?,?,?,?,?)',(news_id,source_id,headline,url,NOW(),independent_group,1 if verified else 0,notes)); c.commit(); c.close(); audit(user['username'],'SOURCE_ATTACHED',f'news={news_id}'); return RedirectResponse('/',303)
@app.post('/news/{news_id}/verify')
def verify_news(news_id:int,user=Depends(require_user)):
    owner_only(user); result=verification_for_news(news_id); c=db(); c.execute('UPDATE news SET confidence=?,status=? WHERE id=?',(result['confidence'],'READY_FOR_REVIEW' if result['decision']=='AUTO_ELIGIBLE' else 'HOLD',news_id)); c.execute('INSERT INTO verification_runs(news_id,independent_sources,total_sources,confidence,conflict,decision,reasons,created_at) VALUES(?,?,?,?,?,?,?,?)',(news_id,result['independent_sources'],result['total_sources'],result['confidence'],0,result['decision'],json.dumps(result['reasons'],ensure_ascii=False),NOW()));
    if result['decision']=='HOLD': c.execute('INSERT INTO hold_queue(news_id,reason,confidence,risk,source_comparison,created_at) VALUES(?,?,?,?,?,?)',(news_id,'Verification gate',result['confidence'],'SENSITIVE' if 'Sensitive story' in result['reasons'] else 'NORMAL',json.dumps(result,ensure_ascii=False),NOW()))
    c.commit(); c.close(); audit(user['username'],'NEWS_VERIFY',f"news={news_id}:{result['decision']}"); return JSONResponse(result)
@app.get('/api/news/{news_id}/verification')
def news_verification(news_id:int,user=Depends(require_user)): return verification_for_news(news_id)
@app.post('/feeds/fetch/{source_id}')
def feed_fetch(source_id:int,user=Depends(require_user)):
    owner_only(user); result=fetch_rss_source(source_id); clusters=rebuild_clusters() if 'error' not in result else []; audit(user['username'],'FEED_FETCH',json.dumps(result,ensure_ascii=False)); return JSONResponse({'fetch':result,'clusters':clusters[:50]})
@app.post('/feeds/fetch-all')
def feed_fetch_all(user=Depends(require_user)):
    owner_only(user); c=db(); ids=[r['id'] for r in c.execute('SELECT id FROM sources WHERE enabled=1').fetchall()]; c.close(); results=[fetch_rss_source(i) for i in ids]; clusters=rebuild_clusters(); audit(user['username'],'FEED_FETCH_ALL',f'sources={len(ids)}'); return JSONResponse({'results':results,'clusters':clusters[:50],'note':'Automatic feed worker is enabled by default and runs every FEED_INTERVAL_SECONDS seconds in this deployment.'})
@app.get('/api/clusters')
def api_clusters(user=Depends(require_user)):
    c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM story_clusters ORDER BY updated_at DESC LIMIT 50')]; c.close(); return rows
@app.get('/api/state')
def state(user=Depends(require_user)):
    c=db(); out={'brand':dict(c.execute('SELECT * FROM brand WHERE id=1').fetchone()),'onair':dict(c.execute('SELECT * FROM onair WHERE id=1').fetchone()),'departments':[dict(x) for x in c.execute('SELECT * FROM departments WHERE enabled=1 ORDER BY name')],'anchors':[dict(x) for x in c.execute('SELECT * FROM anchors ORDER BY id')],'sources':[dict(x) for x in c.execute('SELECT * FROM sources ORDER BY name')],'services':[dict(x) for x in c.execute('SELECT * FROM services ORDER BY name')],'news':[dict(x) for x in c.execute('SELECT * FROM news ORDER BY id DESC LIMIT 30')], 'media':[dict(x) for x in c.execute('SELECT * FROM news_media ORDER BY id DESC LIMIT 100')],'hold':[dict(x) for x in c.execute('SELECT * FROM hold_queue WHERE status="HOLD" ORDER BY id DESC LIMIT 30')],'schedules':[dict(x) for x in c.execute('SELECT * FROM schedules ORDER BY start_at LIMIT 30')],'ads':[dict(x) for x in c.execute('SELECT * FROM ads ORDER BY id DESC LIMIT 20')],'integrations':[dict(x) for x in c.execute('SELECT * FROM integrations ORDER BY name')],'security':dict(c.execute('SELECT * FROM security_settings WHERE id=1').fetchone())}; c.close(); return out
@app.post('/brand/save')
def brand_save(name:str=Form(...),short_name:str=Form(...),tagline:str=Form(...),station_id:str=Form(...),primary_color:str=Form(...),user=Depends(require_user)):
    owner_only(user); c=db(); c.execute('UPDATE brand SET name=?,short_name=?,tagline=?,station_id=?,primary_color=?,updated_at=? WHERE id=1',(name,short_name,tagline,station_id,primary_color,NOW())); c.commit(); c.close(); audit(user['username'],'BRAND_UPDATE',name); return RedirectResponse('/',303)
@app.post('/schedule')
def schedule(title:str=Form(...),start_at:str=Form(...),end_at:str=Form(...),kind:str=Form(...),user=Depends(require_user)):
    owner_only(user); c=db(); c.execute('INSERT INTO schedules(title,start_at,end_at,kind,created_at) VALUES(?,?,?,?,?)',(title,start_at,end_at,kind,NOW())); c.commit(); c.close(); audit(user['username'],'SCHEDULE_ADD',title); return RedirectResponse('/',303)
@app.post('/output/switch')
def output_switch(source:str=Form(...),user=Depends(require_user)):
    owner_only(user); allowed={'DIGITAL_BACKUP','PHYSICAL_STUDIO','EMERGENCY_BACKUP'}
    if source not in allowed: raise HTTPException(400,'Invalid source')
    c=db(); c.execute('UPDATE onair SET source=?,updated_at=? WHERE id=1',(source,NOW())); c.execute('INSERT INTO output_events(event_type,payload,created_at) VALUES(?,?,?)',('SOURCE_SWITCH',source,NOW())); c.commit(); c.close(); audit(user['username'],'OUTPUT_SOURCE_SWITCH',source); return RedirectResponse('/',303)
@app.post('/ads/order')
def ad_order(advertiser:str=Form(...),package:str=Form(...),amount:float=Form(...),user=Depends(require_user)):
    c=db(); c.execute('INSERT INTO ad_orders(advertiser,package,amount,created_at) VALUES(?,?,?,?)',(advertiser,package,amount,NOW())); c.commit(); c.close(); audit(user['username'],'AD_ORDER_CREATED',advertiser); return RedirectResponse('/',303)
@app.post('/call/ticket')
def call_ticket(channel:str=Form(...),caller:str=Form(''),category:str=Form(...),message:str=Form(...),user=Depends(require_user)):
    c=db(); c.execute('INSERT INTO call_tickets(channel,caller,category,message,created_at) VALUES(?,?,?,?,?)',(channel,caller,category,message,NOW())); c.commit(); c.close(); audit(user['username'],'CALL_TICKET_CREATED',category); return RedirectResponse('/',303)
@app.get('/qr/app')
def qr_app(request:Request):
    return StreamingResponse(qr_png(public_base_url(request)+'/app'),media_type='image/png')

@app.get('/qr/ad')
def qr_ad(request:Request):
    return StreamingResponse(qr_png(public_base_url(request)+'/ad'),media_type='image/png')

@app.get('/qr/site')
def qr_site(request:Request):
    return StreamingResponse(qr_png(public_base_url(request)+'/site'),media_type='image/png')

@app.get('/broadcast-qr',response_class=HTMLResponse)
def broadcast_qr(request:Request):
    return templates.TemplateResponse(request=request,name='broadcast_qr.html',context={'app_url':public_base_url(request)+'/app','ad_url':public_base_url(request)+'/ad'})

@app.get('/api/clock')
def api_clock():
    return {'timezone':'Asia/Kolkata','utc':NOW(),'display':ist_now().strftime('%d-%m-%Y %I:%M:%S %p')}

@app.post('/news/{news_id}/approve')
def approve_news(news_id:int,user=Depends(require_user)):
    owner_only(user)
    c=db(); n=c.execute('SELECT * FROM news WHERE id=?',(news_id,)).fetchone()
    if not n:
        c.close(); raise HTTPException(404,'News not found')
    # Publication remains an explicit human/Owner action. Sensitive stories are never auto-approved.
    if n['risk']=='SENSITIVE' or SENSITIVE.search((n['title'] or '')+' '+(n['body'] or '')):
        reason='Sensitive story — explicit Owner approval required'
    else:
        reason='Owner publication approval'
    c.execute("UPDATE news SET status='APPROVED',approved_by=? WHERE id=?",(user['username'],news_id))
    c.execute("UPDATE hold_queue SET status='RESOLVED',resolved_by=? WHERE news_id=? AND status='HOLD'",(user['username'],news_id))
    c.commit(); c.close(); audit(user['username'],'NEWS_APPROVED',f'news={news_id};reason={reason}')
    return JSONResponse({'news_id':news_id,'status':'APPROVED','approved_by':user['username'],'note':reason})

@app.get('/api/automation-status')
def automation_status(user=Depends(require_user)):
    c=db(); rows={}
    for key in ('master_automation_heartbeat','feed_worker_heartbeat'):
        r=c.execute('SELECT value FROM system_settings WHERE key=?',(key,)).fetchone(); rows[key]=r['value'] if r else None
    c.close()
    return {'auto_feed_enabled':AUTO_FEED_ENABLED,'feed_interval_seconds':FEED_INTERVAL,'master_automation':rows['master_automation_heartbeat'],'feed_worker':rows['feed_worker_heartbeat']}

@app.get('/site',response_class=HTMLResponse)
def public_site(request:Request, category:str=''):
    c=db(); b=dict(c.execute('SELECT * FROM brand WHERE id=1').fetchone())
    if category:
        posts=[dict(x) for x in c.execute('SELECT * FROM news WHERE status="APPROVED" AND category LIKE ? ORDER BY id DESC LIMIT 30',(f'%{category}%',)).fetchall()]
    else:
        posts=[dict(x) for x in c.execute('SELECT * FROM news WHERE status="APPROVED" ORDER BY id DESC LIMIT 30').fetchall()]
    today=ist_now().date().isoformat(); future=(ist_now()+timedelta(days=7)).date().isoformat(); festival=c.execute("SELECT * FROM festival_promotions WHERE festival_date BETWEEN ? AND ? ORDER BY festival_date LIMIT 1",(today,future)).fetchone(); promo=c.execute("SELECT * FROM promo_rotation WHERE active=1 ORDER BY priority DESC,id LIMIT 1").fetchone(); c.close(); return templates.TemplateResponse(request=request, name='public_site.html', context={'brand':b,'posts':posts,'category':category,'festival':dict(festival) if festival else None,'promo':dict(promo) if promo else None,'now':ist_now().strftime('%d-%m-%Y %I:%M:%S %p')})

@app.get('/article/{news_id}',response_class=HTMLResponse)
def public_article(request:Request, news_id:int):
    c=db(); post=c.execute('SELECT * FROM news WHERE id=? AND status="APPROVED"',(news_id,)).fetchone()
    if not post: c.close(); raise HTTPException(404,'Article not found')
    media=[dict(x) for x in c.execute('SELECT * FROM news_media WHERE news_id=? ORDER BY id',(news_id,)).fetchall()]
    brand=dict(c.execute('SELECT * FROM brand WHERE id=1').fetchone()); c.close()
    return templates.TemplateResponse(request=request,name='article.html',context={'brand':brand,'post':dict(post),'media':media})

@app.get('/ad',response_class=HTMLResponse)
def public_ad(request:Request):
    packages=[
        {'name':'Basic Website','price':999,'description':'Website banner / basic campaign'},
        {'name':'Video Post','price':1999,'description':'News/social video promotion'},
        {'name':'Live + Video','price':3999,'description':'Live mention + video package'},
        {'name':'Social Combo','price':4999,'description':'Website + social promotion'},
        {'name':'Website + E-paper','price':6999,'description':'Website + e-paper campaign'},
        {'name':'All Platform Mega Combo','price':9999,'description':'Website + video + social package'}]
    return templates.TemplateResponse(request=request,name='ad_public.html',context={'packages':packages})

@app.post('/public-ad/order',response_class=HTMLResponse)
def public_ad_order(advertiser:str=Form(...),package:str=Form(...),amount:float=Form(...),contact_name:str=Form(...),phone:str=Form(...),email:str=Form(...),city:str=Form(...),creative:str=Form(...)):
    c=db(); cur=c.execute('INSERT INTO ad_orders(advertiser,package,amount,payment_status,campaign_status,created_at,contact_name,phone,email,city,creative) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(advertiser,package,amount,'PENDING','DRAFT',NOW(),contact_name,phone,email,city,creative)); oid=cur.lastrowid; c.commit(); c.close(); audit('PUBLIC_AD','AD_ORDER',f'order={oid};advertiser={advertiser};package={package}'); return templates.get_template('ad_success.html').render(order_id=oid)

@app.get('/app',response_class=HTMLResponse)
def public_app(request:Request):
    c=db(); posts=[dict(x) for x in c.execute('SELECT * FROM news WHERE status="APPROVED" ORDER BY id DESC LIMIT 20').fetchall()]; c.close(); return templates.TemplateResponse(request=request,name='app_public.html',context={'posts':posts})

@app.get('/manifest.webmanifest')
def manifest():
    from fastapi.responses import FileResponse
    return FileResponse('app/static/manifest.webmanifest',media_type='application/manifest+json')

@app.get('/sw.js')
def service_worker():
    from fastapi.responses import FileResponse
    return FileResponse('app/static/sw.js',media_type='application/javascript')
