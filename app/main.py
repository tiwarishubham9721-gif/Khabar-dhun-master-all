import os, re, sqlite3, json, hashlib, secrets, urllib.request, urllib.parse, xml.etree.ElementTree as ET, asyncio, threading, time, uuid, mimetypes
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
FEED_INTERVAL=int(os.getenv('FEED_INTERVAL_SECONDS','60'))

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
    CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY, title TEXT, body TEXT, category TEXT, location TEXT, source TEXT, risk TEXT DEFAULT 'NORMAL', confidence REAL DEFAULT 0, status TEXT DEFAULT 'DRAFT', created_at TEXT, approved_by TEXT, priority_score REAL DEFAULT 0, language TEXT DEFAULT 'hi', pipeline_status TEXT DEFAULT 'INGESTED');
    CREATE TABLE IF NOT EXISTS hold_queue(id INTEGER PRIMARY KEY, news_id INTEGER, reason TEXT, confidence REAL, risk TEXT, source_comparison TEXT, status TEXT DEFAULT 'HOLD', created_at TEXT, resolved_by TEXT);
    CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, name TEXT UNIQUE, url TEXT, enabled INTEGER DEFAULT 1, status TEXT DEFAULT 'NOT_CONNECTED', source_kind TEXT DEFAULT 'PUBLIC', monitor_url TEXT, feed_url TEXT, local_priority_weight REAL DEFAULT 1.0);
    CREATE TABLE IF NOT EXISTS story_sources(id INTEGER PRIMARY KEY, news_id INTEGER, source_id INTEGER, headline TEXT, url TEXT, observed_at TEXT, independent_group TEXT, verified INTEGER DEFAULT 0, notes TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS verification_runs(id INTEGER PRIMARY KEY, news_id INTEGER, independent_sources INTEGER DEFAULT 0, total_sources INTEGER DEFAULT 0, confidence REAL DEFAULT 0, conflict INTEGER DEFAULT 0, decision TEXT DEFAULT 'HOLD', reasons TEXT DEFAULT '', created_at TEXT);
    CREATE TABLE IF NOT EXISTS feed_items(id INTEGER PRIMARY KEY, source_id INTEGER, guid TEXT UNIQUE, title TEXT, summary TEXT, url TEXT, published_at TEXT, fetched_at TEXT, cluster_key TEXT, status TEXT DEFAULT 'INGESTED');
    CREATE TABLE IF NOT EXISTS story_clusters(id INTEGER PRIMARY KEY, cluster_key TEXT UNIQUE, title TEXT, item_count INTEGER DEFAULT 0, source_count INTEGER DEFAULT 0, confidence REAL DEFAULT 0, status TEXT DEFAULT 'CANDIDATE', updated_at TEXT);
    CREATE TABLE IF NOT EXISTS schedules(id INTEGER PRIMARY KEY, title TEXT, start_at TEXT, end_at TEXT, kind TEXT, status TEXT DEFAULT 'SCHEDULED', created_at TEXT);
    CREATE TABLE IF NOT EXISTS onair(id INTEGER PRIMARY KEY CHECK(id=1), source TEXT, mode TEXT, current_output_id INTEGER, updated_at TEXT, started_at TEXT);
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
    if not c.execute('SELECT id FROM onair WHERE id=1').fetchone(): c.execute('INSERT INTO onair(source,mode,current_output_id,updated_at,started_at) VALUES(?,?,?,?,?)',("DIGITAL_BACKUP","NORMAL",None,NOW()))
    else:
        cols=[r[1] for r in c.execute('PRAGMA table_info(onair)')];
        if 'current_output_id' not in cols: c.execute('ALTER TABLE onair ADD COLUMN current_output_id INTEGER')
        if 'started_at' not in cols: c.execute('ALTER TABLE onair ADD COLUMN started_at TEXT')
    if not c.execute('SELECT id FROM security_settings WHERE id=1').fetchone(): c.execute('INSERT INTO security_settings VALUES(1,0,?,?)',(NOW(),'SYSTEM'))
    deps=['News Research','Verification','Breaking News','News Desk','Script Writer','Video Production','Graphics','AI Anchor','Shooting / Camera','Music','Programming / Master Control','Video QC','Social Media','WhatsApp','E-paper','Advertisement','Comments','Analytics','Backup / Operations','Weather','Agriculture / Farmers','Health','Education','Science / Technology','Law / Court','Crime / Investigation','Political Analysis','Elections','Business / Economy','Sports','Entertainment / Cinema / OTT','Auto / Travel','Lifestyle','Human Interest','Fact Check','Ground / Local Reporter','Interviews / Dialogue','Debate / Analysis','Special Coverage','Disaster / Emergency','Photo / Video','Live Reporting','Audience / Comments','Podcast / Audio','International','Self Promotion / Publicity','Festival Greetings','Audience Growth / App Promotion']
    for n in deps: c.execute('INSERT OR IGNORE INTO departments(name,category,created_by,created_at) VALUES(?,?,?,?)',(n,'NEWSROOM','SYSTEM',NOW()))
    for n in ['YouTube','Facebook','Instagram','WhatsApp Business','AI Provider','Video Renderer','Voice / TTS','Payment Gateway','Email','SMS / Calling','Cloud / Object Storage','IoT Studio Red Light + Buzzer']: c.execute('INSERT OR IGNORE INTO services(name,kind) VALUES(?,?)',(n,'EXTERNAL'))
    sources=[
('Press Information Bureau','https://pib.gov.in/'),('Election Commission of India','https://www.eci.gov.in/'),('India Meteorological Department','https://mausam.imd.gov.in/'),('RBI','https://www.rbi.org.in/'),('TRAI','https://trai.gov.in/'),('Indian Railways','https://indianrailways.gov.in/'),('Reuters','https://www.reuters.com/'),('The Hindu','https://www.thehindu.com/'),('Indian Express','https://indianexpress.com/'),('Hindustan Times','https://www.hindustantimes.com/'),('BBC News','https://www.bbc.com/news'),('ANI','https://www.aninews.in/'),
('Aaj Tak — Public Monitor','https://www.aajtak.in/'),('ABP News — Public Monitor','https://www.abplive.com/'),('India TV — Public Monitor','https://www.indiatvnews.com/'),('News18 India — Public Monitor','https://hindi.news18.com/'),('Zee News — Public Monitor','https://zeenews.india.com/hindi'),('TV9 Bharatvarsh — Public Monitor','https://www.tv9hindi.com/'),('NDTV India — Public Monitor','https://ndtv.in/'),('Times Now Navbharat — Public Monitor','https://www.timesnowhindi.com/'),('Republic Bharat — Public Monitor','https://www.republicbharat.com/'),('News24 — Public Monitor','https://news24online.com/'),('CNBC Awaaz — Public Monitor','https://hindi.cnbctv18.com/'),('DD News — Public Monitor','https://ddinews.gov.in/')]
    for n,u in sources: c.execute('INSERT OR IGNORE INTO sources(name,url,status,source_kind,monitor_url) VALUES(?,?,?,?,?)',(n,u,'PARTIAL' if 'Public Monitor' in n else 'NOT_CONNECTED','PUBLIC',u))
    # Verified public RSS endpoints where available; other sources remain public-monitor/ACTION_REQUIRED rather than pretending to have a feed.
    verified_feeds={
        # Public RSS feeds explicitly exposed by the publishers / publisher ecosystem.
        'Aaj Tak — Public Monitor':'https://www.aajtak.in/rssfeeds/?id=home',
        'ABP News — Public Monitor':'https://www.abplive.com/home/feed',
        'News18 India — Public Monitor':'https://www.news18.com/rss/india.xml',
        'NDTV India — Public Monitor':'https://feeds.feedburner.com/ndtvkhabar-latest',
        'Republic Bharat — Public Monitor':'https://www.republicbharat.com/rss',
    }
    for n,u in verified_feeds.items():
        c.execute("UPDATE sources SET feed_url=?,url=?,status='FEED_CONFIGURED' WHERE name=?",(u,u,n))
    for n in ['YouTube','Facebook','Instagram','WhatsApp Business']: c.execute('INSERT OR IGNORE INTO integrations(name) VALUES(?)',(n,))
    for n in ['Anchor 1','Anchor 2','Anchor 3']: c.execute('INSERT OR IGNORE INTO anchors(name,created_at) VALUES(?,?)',(n,NOW()))
    # Safe migrations for existing databases
    try: c.execute('ALTER TABLE news ADD COLUMN cluster_key TEXT')
    except Exception: pass
    for col,typ in [("source_kind","TEXT DEFAULT 'PUBLIC'"),("monitor_url","TEXT"),("feed_url","TEXT"),("local_priority_weight","REAL DEFAULT 1.0"),("last_checked_at","TEXT")]:
        try: c.execute(f'ALTER TABLE sources ADD COLUMN {col} {typ}')
        except Exception: pass
    for col,typ in [("priority_score","REAL DEFAULT 0"),("language","TEXT DEFAULT 'hi'"),("pipeline_status","TEXT DEFAULT 'INGESTED'")]:
        try: c.execute(f'ALTER TABLE news ADD COLUMN {col} {typ}')
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
    url=(src['feed_url'] or src['url'] or '')
    if not url.startswith(('http://','https://')): c.close(); return {'error':'feed URL not configured'}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'KHABAR-DHUN-NewsEngine/3.0'})
        data=urllib.request.urlopen(req,timeout=timeout).read(); root=ET.fromstring(data); items=[]
        for item in root.findall('.//item')[:100]:
            title=(item.findtext('title') or '').strip(); link=(item.findtext('link') or '').strip(); guid=(item.findtext('guid') or link or title).strip(); summary=(item.findtext('description') or '').strip(); pub=(item.findtext('pubDate') or '').strip()
            if not title: continue
            ck=cluster_key(title); c.execute('INSERT OR IGNORE INTO feed_items(source_id,guid,title,summary,url,published_at,fetched_at,cluster_key) VALUES(?,?,?,?,?,?,?,?)',(source_id,guid,title,summary,link,pub,NOW(),ck)); items.append({'title':title,'url':link,'cluster_key':ck})
        c.execute('UPDATE sources SET status=?, last_checked_at=? WHERE id=?',('FETCHED',NOW(),source_id)); c.commit(); c.close(); return {'source':src['name'],'items':len(items),'items_preview':items[:10]}
    except Exception as e:
        try:
            c.execute('UPDATE sources SET status=?, last_checked_at=? WHERE id=?',('ERROR',NOW(),source_id)); c.commit()
        except Exception: pass
        c.close(); return {'source':src['name'],'error':str(e),'note':'Automatic worker will retry on the next cycle.'}

def rebuild_clusters():
    c=db(); groups={}
    for r in c.execute('SELECT cluster_key, title, source_id FROM feed_items ORDER BY fetched_at DESC LIMIT 2000').fetchall(): groups.setdefault(r['cluster_key'],[]).append(r)
    out=[]
    for k,rows in groups.items():
        title=rows[0]['title']; sc=len(set(x['source_id'] for x in rows)); conf=min(.99,sc/8); c.execute('INSERT INTO story_clusters(cluster_key,title,item_count,source_count,confidence,status,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(cluster_key) DO UPDATE SET title=excluded.title,item_count=excluded.item_count,source_count=excluded.source_count,confidence=excluded.confidence,updated_at=excluded.updated_at',(k,title,len(rows),sc,conf,'CANDIDATE',NOW())); out.append({'cluster_key':k,'title':title,'item_count':len(rows),'source_count':sc,'confidence':conf})
    c.commit(); c.close(); return out

LOCAL_PRIORITY_AREAS={'gonda':1.8,'ayodhya':1.8,'faizabad':1.6,'lucknow':1.4,'uttar pradesh':1.3,'up':1.2}
def local_priority_score(title,summary=''):
    text=((title or '')+' '+(summary or '')).lower()
    score=1.0
    for k,w in LOCAL_PRIORITY_AREAS.items():
        if k in text: score=max(score,w)
    return score

def infer_category(title, summary=''):
    text=((title or '')+' '+(summary or '')).lower()
    rules=[
        ('राजनीति',('politic','चुनाव','सरकार','मंत्री','सांसद','विधायक','बीजेपी','कांग्रेस','भाजपा')),
        ('खेल',('cricket','football','sports','खेल','मैच','खिलाड़ी')),
        ('बिजनेस',('business','economy','बिजनेस','अर्थव्यवस्था','बैंक','शेयर','रुपये','महंगाई')),
        ('मनोरंजन',('entertainment','bollywood','फिल्म','मनोरंजन','अभिनेता','अभिनेत्री')),
        ('टेक्नोलॉजी',('technology','tech','टेक्नोलॉजी','मोबाइल','ai','कृत्रिम बुद्धिमत्ता')),
        ('स्थानीय',('gonda','गोंडा','ayodhya','अयोध्या','faizabad','फैजाबाद','lucknow','लखनऊ','uttar pradesh','उत्तर प्रदेश'))
    ]
    for cat,keys in rules:
        if any(k in text for k in keys): return cat
    return 'राष्ट्रीय'

def infer_location(title, summary=''):
    text=((title or '')+' '+(summary or '')).lower()
    for k,label in [('gonda','Gonda'),('गोंडा','Gonda'),('ayodhya','Ayodhya'),('अयोध्या','Ayodhya'),('faizabad','Ayodhya'),('फैजाबाद','Ayodhya'),('lucknow','Lucknow'),('लखनऊ','Lucknow'),('uttar pradesh','Uttar Pradesh'),('उत्तर प्रदेश','Uttar Pradesh')]:
        if k in text: return label
    return ''

def pipeline_for_news(news_id, auto_outputs=False):
    c=db(); n=c.execute('SELECT * FROM news WHERE id=?',(news_id,)).fetchone()
    if not n: c.close(); return {'status':'ERROR','error':'news not found'}
    score=local_priority_score(n['title'],n['body'])
    c.execute('UPDATE news SET priority_score=?,pipeline_status=? WHERE id=?',(score,'ANALYZING',news_id))
    c.commit(); c.close()
    vr=verification_for_news(news_id)
    c=db(); c.execute('UPDATE news SET confidence=?,pipeline_status=? WHERE id=?',(vr['confidence'],'VERIFIED' if vr['decision']=='AUTO_ELIGIBLE' else 'HOLD',news_id))
    outputs=[]
    if vr['decision']=='AUTO_ELIGIBLE' and auto_outputs:
        for channel,fmt in [('WEBSITE','ARTICLE'),('APP','ARTICLE'),('EPAPER','ARTICLE'),('YOUTUBE','VIDEO_OR_PHOTO'),('FACEBOOK','POST'),('INSTAGRAM','POST'),('WHATSAPP','UPDATE')]:
            status='QUEUED' if channel in {'WEBSITE','APP','EPAPER'} else 'WAITING_CONNECTION'
            c.execute('INSERT INTO content_outputs(news_id,channel,format,status,created_at,updated_at) VALUES(?,?,?,?,?,?)',(news_id,channel,fmt,status,NOW(),NOW()))
            outputs.append({'channel':channel,'status':status})
    c.commit(); c.close()
    return {'status':'VERIFIED' if vr['decision']=='AUTO_ELIGIBLE' else 'HOLD','verification':vr,'local_priority_score':score,'outputs':outputs}

def auto_promote_feed_clusters():
    c=db(); created=0
    rows=c.execute('SELECT cluster_key,title,item_count,source_count,confidence FROM story_clusters WHERE item_count>0 ORDER BY updated_at DESC LIMIT 200').fetchall()
    for cl in rows:
        if c.execute('SELECT id FROM news WHERE cluster_key=?',(cl['cluster_key'],)).fetchone(): continue
        item=c.execute('SELECT summary,url,source_id FROM feed_items WHERE cluster_key=? ORDER BY fetched_at DESC LIMIT 1',(cl['cluster_key'],)).fetchone()
        if not item: continue
        srcs=c.execute('SELECT name FROM sources WHERE id IN (SELECT DISTINCT source_id FROM feed_items WHERE cluster_key=?)',(cl['cluster_key'],)).fetchall()
        source_text=', '.join(x['name'] for x in srcs[:12])
        summary=(item['summary'] or 'Automatic source feed intake; original report linked below.')[:12000]
        risk='SENSITIVE' if SENSITIVE.search(cl['title'] or '') else 'NORMAL'
        category=infer_category(cl['title'],summary)
        location=infer_location(cl['title'],summary)
        # A configured publisher feed is source-verified, but sensitive stories still require human review.
        # Normal source-backed stories can appear automatically on KHABAR DHUN with source attribution.
        status='HOLD' if risk=='SENSITIVE' else 'APPROVED'
        pipeline='HOLD_SENSITIVE' if risk=='SENSITIVE' else 'SOURCE_VERIFIED_AUTO'
        cur=c.execute('INSERT INTO news(title,body,category,location,source,risk,confidence,status,created_at,cluster_key,pipeline_status,priority_score) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(cl['title'],summary,category,location,source_text,risk,cl['confidence'],status,NOW(),cl['cluster_key'],pipeline,local_priority_score(cl['title'],summary)))
        nid=cur.lastrowid
        # Preserve every source observation so the verification engine can corroborate later.
        cluster_items=c.execute('SELECT source_id,title,url,published_at FROM feed_items WHERE cluster_key=? ORDER BY fetched_at DESC',(cl['cluster_key'],)).fetchall()
        for obs in cluster_items:
            srcrow=c.execute('SELECT name FROM sources WHERE id=?',(obs['source_id'],)).fetchone()
            if not srcrow: continue
            c.execute('INSERT INTO story_sources(news_id,source_id,headline,url,observed_at,independent_group,verified,notes) VALUES(?,?,?,?,?,?,?,?)',(nid,obs['source_id'],obs['title'],obs['url'],NOW(),srcrow['name'],1,'Publisher feed successfully fetched'))
        if risk=='SENSITIVE':
            c.execute('INSERT INTO hold_queue(news_id,reason,confidence,risk,source_comparison,created_at) VALUES(?,?,?,?,?,?)',(nid,'Sensitive story requires human verification before publication',cl['confidence'],risk,source_text,NOW()))
        else:
            c.execute('INSERT INTO verification_runs(news_id,independent_sources,total_sources,confidence,conflict,decision,reasons,created_at) VALUES(?,?,?,?,?,?,?,?)',(nid,cl['source_count'],cl['source_count'],cl['confidence'],0,'SOURCE_VERIFIED','Publisher feed fetched successfully; automatic publication allowed only for non-sensitive source-backed stories.',NOW()))
        # Route every automatically approved story into the real newsroom department queue.
        if status=='APPROVED':
            pipeline_for_news(cur.lastrowid, auto_outputs=True)
            route_departments_for_news(cur.lastrowid)
        created+=1
    c.commit(); c.close(); return created

def route_departments_for_news(news_id):
    """Create one auditable job per relevant newsroom department.
    Jobs are real workflow records; external rendering/publishing is only marked complete after the corresponding worker/connection succeeds.
    """
    c=db(); n=c.execute('SELECT * FROM news WHERE id=?',(news_id,)).fetchone()
    if not n: c.close(); return 0
    title=n['title'] or ''; body=n['body'] or ''; cat=n['category'] or ''
    jobs=[]
    base=['News Research','Verification','News Desk','Script Writer','Graphics','Photo / Video','Video Production','Video QC','Social Media','E-paper','Analytics']
    if cat=='राजनीति' or n['risk']=='SENSITIVE': base += ['Political Analysis','Fact Check']
    if n['location'] in ('Gonda','Ayodhya','Lucknow','Uttar Pradesh'): base += ['Ground / Local Reporter','Special Coverage']
    for dept in dict.fromkeys(base):
        payload={'news_id':news_id,'title':title,'category':cat,'location':n['location'],'instruction':'Process this story according to department SOP; do not invent facts.'}
        cur=c.execute('INSERT INTO dept_jobs(department,input_json,status,attempts,created_at,updated_at) VALUES(?,?,?,?,?,?)',(dept,json.dumps(payload,ensure_ascii=False),'QUEUED',0,NOW(),NOW()))
        jobs.append(cur.lastrowid)
    c.execute('UPDATE news SET pipeline_status=? WHERE id=?',('DEPARTMENT_ROUTING',news_id))
    c.commit(); c.close(); return len(jobs)

def department_worker_cycle():
    c=db(); rows=c.execute("SELECT * FROM dept_jobs WHERE status='QUEUED' ORDER BY id LIMIT 50").fetchall()
    for r in rows:
        try:
            payload=json.loads(r['input_json'] or '{}'); dept=r['department']; out={'news_id':payload.get('news_id'),'department':dept,'status':'COMPLETED'}
            # Department-specific deterministic work that is safe without external credentials.
            if dept=='News Desk': out['article_ready']=True
            elif dept=='Script Writer': out['script_ready']=True
            elif dept in ('Graphics','Photo / Video'): out['asset_request_ready']=True
            elif dept=='Video Production': out['video_status']='RENDERER_CONNECTION_REQUIRED'
            elif dept=='Video QC': out['qc_status']='WAITING_FOR_VIDEO'
            elif dept=='E-paper': out['epaper_ready']=True
            elif dept=='Social Media': out['platform_publish']='CONNECTION_REQUIRED'
            elif dept=='Verification': out['verification']='ALREADY_SOURCE_VERIFIED_OR_HOLD'
            else: out['work_item']='ROUTED_AND_AUDITED'
            status='COMPLETED' if dept not in ('Video Production','Video QC','Social Media') else 'WAITING_CONNECTION'
            err=None if status=='COMPLETED' else 'External video/social connection required'
            c.execute('UPDATE dept_jobs SET status=?,output_json=?,attempts=attempts+1,error=?,updated_at=? WHERE id=?',(status,json.dumps(out,ensure_ascii=False),err,NOW(),r['id']))
        except Exception as e:
            c.execute("UPDATE dept_jobs SET status='ERROR',attempts=attempts+1,error=?,updated_at=? WHERE id=?",(str(e),NOW(),r['id']))
    c.commit(); c.close()

def department_worker():
    while True:
        try: department_worker_cycle()
        except Exception: pass
        time.sleep(5)

threading.Thread(target=department_worker,name='khabar-dhun-department-worker',daemon=True).start()

def youtube_monitor_cycle():
    """Monitor official YouTube channels when YOUTUBE_API_KEY is configured.
    Uses the YouTube Data API only; it does not scrape or rebroadcast private/paid streams.
    """
    key=os.getenv('YOUTUBE_API_KEY','').strip()
    if not key:
        return {'status':'ACTION_REQUIRED','channels':0,'items':0}
    total=0; live=0; errors=0
    c=db()
    for name,handle,url in LIVE_CHANNELS:
        try:
            q=urllib.parse.urlencode({'part':'id','forHandle':handle,'key':key})
            with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/channels?'+q,timeout=8) as r:
                data=json.loads(r.read().decode())
            items=data.get('items',[])
            if not items:
                continue
            cid=items[0]['id']
            # Latest uploads (including non-live breaking updates).
            q2=urllib.parse.urlencode({'part':'snippet','channelId':cid,'order':'date','type':'video','maxResults':5,'key':key})
            with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/search?'+q2,timeout=8) as r:
                latest=json.loads(r.read().decode()).get('items',[])
            for it in latest:
                sn=it.get('snippet',{}); vid=(it.get('id') or {}).get('videoId')
                title=(sn.get('title') or '').strip()
                if not title or not vid: continue
                guid='yt:'+vid
                pub=sn.get('publishedAt','')
                link='https://www.youtube.com/watch?v='+vid
                c.execute('INSERT OR IGNORE INTO feed_items(source_id,guid,title,summary,url,published_at,fetched_at,cluster_key) SELECT id,?,?,?,?,?,?,? FROM sources WHERE name=?',(guid,title,sn.get('description','')[:12000],link,pub,NOW(),cluster_key(title),name))
                total += 1
            q3=urllib.parse.urlencode({'part':'snippet','channelId':cid,'eventType':'live','type':'video','maxResults':1,'key':key})
            with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/search?'+q3,timeout=8) as r:
                li=json.loads(r.read().decode()).get('items',[])
            if li: live += 1
            c.execute('UPDATE sources SET status=?,last_checked_at=? WHERE name=?',('YOUTUBE_MONITORED',NOW(),name))
        except Exception:
            errors += 1
            try: c.execute('UPDATE sources SET status=?,last_checked_at=? WHERE name=?',('ERROR',NOW(),name))
            except Exception: pass
    c.commit(); c.close()
    return {'status':'CONNECTED','channels':len(LIVE_CHANNELS),'items':total,'live_channels':live,'errors':errors}

def automatic_feed_cycle():
    set_automation_heartbeat('feed_worker')
    ensure_feed_urls()
    try: youtube_monitor_cycle()
    except Exception: pass
    c=db(); ids=[r['id'] for r in c.execute('SELECT id FROM sources WHERE enabled=1 AND feed_url IS NOT NULL AND feed_url!=''').fetchall()]; c.close()
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
        time.sleep(max(15,FEED_INTERVAL))

def start_feed_worker():
    if not AUTO_FEED_ENABLED: return
    t=threading.Thread(target=feed_worker,name='khabar-dhun-feed-worker',daemon=True); t.start()

start_feed_worker()

def verification_for_news(nid):
    c=db(); n=c.execute('SELECT * FROM news WHERE id=?',(nid,)).fetchone(); rows=c.execute('SELECT ss.*,s.name FROM story_sources ss JOIN sources s ON s.id=ss.source_id WHERE ss.news_id=?',(nid,)).fetchall(); c.close()
    if not n: raise HTTPException(404,'News not found')
    groups={r['independent_group'] or r['name'] for r in rows}; verified=[r for r in rows if r['verified']]; reasons=[]
    if n['risk']=='SENSITIVE' or SENSITIVE.search((n['title'] or '')+' '+(n['body'] or '')): reasons.append('Sensitive story')
    if len(groups)<2: reasons.append('Fewer than 2 independent sources for corroborated verification')
    if len(verified)<2: reasons.append('Fewer than 2 verified observations for corroborated verification')
    decision='AUTO_ELIGIBLE' if not reasons else 'HOLD'; return {'news_id':nid,'independent_sources':len(groups),'total_sources':len(rows),'verified_observations':len(verified),'confidence':min(.99,len(groups)/2),'decision':decision,'reasons':reasons}

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

ELECTION_TERMS=re.compile(r'\b(election|elections|poll|polling|vote|voting|result|results|assembly|lok sabha|by-election|उपचुनाव|चुनाव|मतदान|वोटिंग|नतीजे|परिणाम|निर्वाचन)\b',re.I)
MONITORED_CHANNELS=['Aaj Tak — Public Monitor','ABP News — Public Monitor','India TV — Public Monitor','News18 India — Public Monitor','Zee News — Public Monitor','TV9 Bharatvarsh — Public Monitor','NDTV India — Public Monitor','Times Now Navbharat — Public Monitor','Republic Bharat — Public Monitor','News24 — Public Monitor','CNBC Awaaz — Public Monitor','DD News — Public Monitor']
def scan_election_signals():
    c=db(); rows=c.execute("SELECT title,summary,source_id,fetched_at FROM feed_items ORDER BY fetched_at DESC LIMIT 500").fetchall(); hits=[r for r in rows if ELECTION_TERMS.search((r['title'] or '')+' '+(r['summary'] or ''))]; now=NOW(); reason=f"{len(hits)} recent election/poll signal(s) detected from monitored feeds" if hits else 'No election signal detected in configured feeds'; c.execute("UPDATE election_state SET active=?,mode=?,trigger_reason=?,detected_at=COALESCE(detected_at,?),last_scan_at=? WHERE id=1",(1 if hits else 0,'ELECTION_ACTIVE' if hits else 'NORMAL',reason,now,now)); c.commit(); c.close(); return {'active':bool(hits),'hits':len(hits),'reason':reason,'last_scan_at':now}
def source_monitor_snapshot():
    c=db(); rows=[]
    for n in MONITORED_CHANNELS:
        r=c.execute('SELECT name,status,feed_url,monitor_url,last_checked_at FROM sources WHERE name=?',(n,)).fetchone(); rows.append(dict(r) if r else {'name':n,'status':'NOT_REGISTERED','feed_url':None,'monitor_url':None,'last_checked_at':None})
    c.close(); return rows

def automation_cycle():
    try:
        set_automation_heartbeat('master_automation'); seed_self_promotion(); seed_festival_promotions(ist_now().year)
        c=db(); ids=[r['id'] for r in c.execute("SELECT id FROM sources WHERE enabled=1 AND feed_url IS NOT NULL AND feed_url!=''").fetchall()]; c.close()
        for sid in ids:
            try: fetch_rss_source(sid,timeout=10)
            except Exception: pass
        try: rebuild_clusters()
        except Exception: pass
        scan_election_signals()
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
@app.post('/pipeline/run/{news_id}')
def pipeline_run(news_id:int, auto_outputs:bool=False, user=Depends(require_user)):
    owner_only(user); result=pipeline_for_news(news_id,auto_outputs=auto_outputs); v5_audit(user,'PIPELINE_RUN',json.dumps(result,ensure_ascii=False)); return result

@app.post('/automation/self-promotion/rotate')
def rotate_self_promotion(user=Depends(require_user)):
    owner_only(user); c=db(); rows=c.execute('SELECT * FROM promo_rotation WHERE active=1 ORDER BY priority DESC,id').fetchall()
    if not rows: seed_self_promotion(); rows=c.execute('SELECT * FROM promo_rotation WHERE active=1 ORDER BY priority DESC,id').fetchall()
    idx=int(time.time()//300)%len(rows); selected=rows[idx]
    c.execute("INSERT INTO system_settings(key,value) VALUES('active_promo_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(selected['id']),)); c.commit(); c.close(); v5_audit(user,'SELF_PROMOTION_ROTATE',str(selected['id'])); return {'status':'FUNCTIONAL','selected':dict(selected),'rotation_minutes':5}

@app.get('/api/festival')
def festival_api(user=Depends(require_user)):
    c=db(); today=ist_now().date().isoformat(); rows=[dict(x) for x in c.execute('SELECT * FROM festival_promotions WHERE festival_date>=? ORDER BY festival_date LIMIT 30',(today,))]; c.close(); return rows

@app.get('/api/connections')
def connections_api(user=Depends(require_user)):
    c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM connections ORDER BY provider')]; c.close(); return rows

@app.get('/api/source-registry')
def source_registry(user=Depends(require_user)):
    c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM sources ORDER BY name')]; c.close(); return rows

@app.post('/feeds/fetch-all')
def feed_fetch_all(user=Depends(require_user)):
    owner_only(user); c=db(); ids=[r['id'] for r in c.execute('SELECT id FROM sources WHERE enabled=1 AND feed_url IS NOT NULL AND feed_url!=''').fetchall()]; c.close(); results=[fetch_rss_source(i) for i in ids]; clusters=rebuild_clusters(); audit(user['username'],'FEED_FETCH_ALL',f'sources={len(ids)}'); return JSONResponse({'results':results,'clusters':clusters[:50],'note':'Automatic feed worker is enabled by default and runs every FEED_INTERVAL_SECONDS seconds in this deployment.'})
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
    # Independent output jobs: internal destinations can be delivered by this app; external destinations wait for verified connections.
    for channel, fmt in [('WEBSITE','ARTICLE'),('APP','ARTICLE'),('EPAPER','ARTICLE'),('LCD','FINAL_OUTPUT'),('YOUTUBE','VIDEO'),('FACEBOOK','POST'),('INSTAGRAM','POST'),('WHATSAPP','UPDATE')]:
        c.execute("INSERT INTO content_outputs(news_id,channel,format,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",(news_id,channel,fmt,'QUEUED',NOW(),NOW()))
    c.commit(); c.close(); audit(user['username'],'NEWS_APPROVED',f'news={news_id};reason={reason}')
    process_internal_outputs()
    return JSONResponse({'news_id':news_id,'status':'APPROVED','approved_by':user['username'],'note':reason,'outputs':'CREATED'})

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

@app.get('/referral',response_class=HTMLResponse)
def public_referral(request:Request, ref:str=''):
    code=(ref or '').strip()
    if code:
        c=db(); c.execute('INSERT INTO referral_clicks(code,ip_hash,created_at) VALUES(?,?,?)',(code,hashlib.sha256((request.client.host if request.client else 'unknown').encode()).hexdigest(),NOW())); c.commit(); c.close()
    return HTMLResponse(f'''<!doctype html><html lang=\"hi\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>KHABAR DHUN Referral</title><style>body{{font-family:Arial;background:#07101d;color:#eef5ff;margin:0}}main{{max-width:700px;margin:40px auto;padding:22px}}.card{{background:#101c2d;border:1px solid #263b58;border-radius:14px;padding:22px}}a,button{{display:inline-block;background:#19a7ff;color:#00101c;padding:11px 16px;border-radius:8px;text-decoration:none;font-weight:800;border:0;margin:5px 0}}</style><main><div class=card><h1>KHABAR DHUN Referral Program</h1><p>KHABAR DHUN App/Network से जुड़ें और eligible referral rewards के लिए अपना referral link share करें।</p><p>Referral code: <b>{code or 'आपके account से generate होगा'}</b></p><a href=\"/app\">KHABAR DHUN App खोलें</a><a href=\"/site\">Website खोलें</a></div></main></html>''')

@app.post('/referral/code')
def referral_code(owner_key:str=Form(...),user=Depends(require_user)):
    owner_only(user); clean=re.sub(r'[^A-Za-z0-9]','',owner_key.upper())[:20] or 'KD'
    code='KD-'+clean+'-'+secrets.token_hex(3).upper()
    c=db(); c.execute('INSERT INTO referral_codes(code,owner_key,created_at) VALUES(?,?,?)',(code,owner_key,NOW())); c.commit(); c.close(); v5_audit(user,'REFERRAL_CODE_CREATED',code); return {'status':'ACTIVE','code':code,'url':'/referral?ref='+code}

@app.get('/api/referrals')
def referrals_api(user=Depends(require_user)):
    c=db(); codes=[dict(x) for x in c.execute('SELECT * FROM referral_codes ORDER BY id DESC LIMIT 100')]; refs=[dict(x) for x in c.execute('SELECT * FROM referrals ORDER BY id DESC LIMIT 100')]; clicks=[dict(x) for x in c.execute('SELECT * FROM referral_clicks ORDER BY id DESC LIMIT 100')]; c.close(); return {'codes':codes,'referrals':refs,'clicks':clicks}

@app.get('/api/source-monitor')
def source_monitor(user=Depends(require_user)):
    snap=source_monitor_snapshot()
    for x in snap:
        x['truth_status']='LIVE' if x.get('status') in ('FETCHED','YOUTUBE_MONITORED') and x.get('last_checked_at') else ('FEED_CONFIGURED' if x.get('feed_url') else ('YOUTUBE_API_MONITOR' if os.getenv('YOUTUBE_API_KEY','').strip() else 'ACTION_REQUIRED'))
    return {'channels':snap,'rule':'LIVE is shown only after a real configured feed has been fetched successfully; no public page is treated as a feed without a lawful/verified connector.'}

@app.get('/api/pipeline-health')
def pipeline_health(user=Depends(require_user)):
    c=db();
    q=lambda sql:c.execute(sql).fetchone()[0]
    out={
      'feed_worker': {'enabled':AUTO_FEED_ENABLED,'interval_seconds':FEED_INTERVAL,'heartbeat':None},
      'news_intake': q('SELECT COUNT(*) FROM news'),
      'approved_public_articles': q("SELECT COUNT(*) FROM news WHERE status='APPROVED'"),
      'department_queued_or_waiting': q("SELECT COUNT(*) FROM dept_jobs WHERE status IN ('QUEUED','WAITING_CONNECTION','PROCESSING')"),
      'website_outputs': q("SELECT COUNT(*) FROM content_outputs WHERE channel='WEBSITE' AND status='DELIVERED'"),
      'app_outputs': q("SELECT COUNT(*) FROM content_outputs WHERE channel='APP' AND status='DELIVERED'"),
      'external_waiting': q("SELECT COUNT(*) FROM content_outputs WHERE status='WAITING_CONNECTION'"),
    }
    hb=c.execute("SELECT value FROM system_settings WHERE key='feed_worker_heartbeat'").fetchone(); out['feed_worker']['heartbeat']=hb['value'] if hb else None
    c.close(); return out

@app.get('/api/election-desk')
def election_desk(user=Depends(require_user)):
    c=db(); state=dict(c.execute('SELECT * FROM election_state WHERE id=1').fetchone()); signals=[dict(x) for x in c.execute("SELECT f.title,f.summary,f.url,f.published_at,f.fetched_at,s.name source FROM feed_items f JOIN sources s ON s.id=f.source_id WHERE lower(f.title) GLOB '*election*' OR lower(f.title) GLOB '*poll*' OR lower(f.title) GLOB '*vote*' OR f.title LIKE '%चुनाव%' OR f.title LIKE '%मतदान%' ORDER BY f.fetched_at DESC LIMIT 100")]; seats=[dict(x) for x in c.execute('SELECT * FROM election_seats ORDER BY updated_at DESC LIMIT 100')]; c.close(); return {'desk':'SEPARATE_ELECTION_DESK','state':state,'signals':signals,'seats':seats,'normal_news_monitoring':'CONTINUES'}

@app.post('/election-desk/scan')
def election_scan(user=Depends(require_user)):
    owner_required(user); result=scan_election_signals(); v5_audit(user,'ELECTION_DESK_SCAN',json.dumps(result,ensure_ascii=False)); return result

@app.get('/api/politics')
def politics_api(user=Depends(require_user)):
    c=db(); sources=[dict(x) for x in c.execute("SELECT name,url,status,source_kind,monitor_url,feed_url,local_priority_weight FROM sources WHERE name LIKE '%Public Monitor%' OR name IN ('Press Information Bureau','Election Commission of India') ORDER BY name")]; watches=[dict(x) for x in c.execute('SELECT * FROM politics_watch ORDER BY observed_at DESC LIMIT 100')]; seats=[dict(x) for x in c.execute('SELECT * FROM election_seats ORDER BY updated_at DESC LIMIT 100')]; c.close(); return {'source_registry':sources,'watch':watches,'election_seats':seats,'rule':'Public/authorized source signals only; no private access or content copying.'}

@app.post('/politics/watch')
def politics_watch(subject:str=Form(...),constituency:str=Form(''),party:str=Form(''),event_type:str=Form(''),source:str=Form(''),user=Depends(require_user)):
    owner_only(user); c=db(); c.execute('INSERT INTO politics_watch(subject,constituency,party,event_type,source,observed_at) VALUES(?,?,?,?,?,?)',(subject,constituency,party,event_type,source,NOW())); c.commit(); c.close(); v5_audit(user,'POLITICS_WATCH_ADD',subject); return {'status':'WATCHING'}

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

# ===== V5 PRODUCTION OPERATIONS EXTENSION =====
def v5_init():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS contributors(id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, district TEXT, status TEXT DEFAULT 'ACTIVE', created_at TEXT);
    CREATE TABLE IF NOT EXISTS contributor_submissions(id INTEGER PRIMARY KEY, contributor_id INTEGER, title TEXT, body TEXT, category TEXT, location TEXT, status TEXT DEFAULT 'PREPROCESSING', qc_status TEXT DEFAULT 'PENDING', news_id INTEGER, reward REAL DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY, referrer TEXT, referred TEXT, status TEXT DEFAULT 'PENDING', reward REAL DEFAULT 0, created_at TEXT, approved_at TEXT);
    CREATE TABLE IF NOT EXISTS referral_codes(id INTEGER PRIMARY KEY, code TEXT UNIQUE, owner_key TEXT, active INTEGER DEFAULT 1, created_at TEXT);
    CREATE TABLE IF NOT EXISTS referral_clicks(id INTEGER PRIMARY KEY, code TEXT, ip_hash TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS wallets(id INTEGER PRIMARY KEY, owner_type TEXT, owner_key TEXT UNIQUE, balance REAL DEFAULT 0, pending REAL DEFAULT 0, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS wallet_ledger(id INTEGER PRIMARY KEY, owner_type TEXT, owner_key TEXT, kind TEXT, amount REAL, reference TEXT, status TEXT DEFAULT 'PENDING', created_at TEXT);
    CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, role TEXT, district TEXT, base_salary REAL DEFAULT 0, incentive_rate REAL DEFAULT 0, active INTEGER DEFAULT 1, created_at TEXT);
    CREATE TABLE IF NOT EXISTS payroll_rules(id INTEGER PRIMARY KEY CHECK(id=1), payment_day INTEGER DEFAULT 5, cutoff_day INTEGER DEFAULT 28, reminder_days INTEGER DEFAULT 3, updated_at TEXT, updated_by TEXT);
    CREATE TABLE IF NOT EXISTS payroll_entries(id INTEGER PRIMARY KEY, employee_id INTEGER, period TEXT, base_salary REAL, incentives REAL, bonuses REAL, deductions REAL, payable REAL, status TEXT DEFAULT 'PENDING', due_date TEXT, paid_at TEXT, transaction_ref TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS payout_accounts(id INTEGER PRIMARY KEY, owner_type TEXT, owner_key TEXT, provider TEXT, masked_account TEXT, status TEXT DEFAULT 'NOT_CONNECTED', secret_ref TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS brand_assets(id INTEGER PRIMARY KEY, name TEXT UNIQUE, kind TEXT, path TEXT, version INTEGER DEFAULT 1, active INTEGER DEFAULT 1, rights_status TEXT DEFAULT 'UNKNOWN', created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS dept_jobs(id INTEGER PRIMARY KEY, department TEXT, input_json TEXT, output_json TEXT, status TEXT DEFAULT 'QUEUED', attempts INTEGER DEFAULT 0, error TEXT, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS politics_watch(id INTEGER PRIMARY KEY, subject TEXT, constituency TEXT, party TEXT, event_type TEXT, source TEXT, observed_at TEXT, status TEXT DEFAULT 'WATCH');
    CREATE TABLE IF NOT EXISTS election_seats(id INTEGER PRIMARY KEY, state TEXT, constituency TEXT, candidate TEXT, party TEXT, phase TEXT, turnout REAL, result_status TEXT DEFAULT 'NOT_PUBLISHED', official_source TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS election_state(id INTEGER PRIMARY KEY CHECK(id=1), active INTEGER DEFAULT 0, trigger_reason TEXT DEFAULT '', detected_at TEXT, last_scan_at TEXT, mode TEXT DEFAULT 'NORMAL');
    CREATE TABLE IF NOT EXISTS oauth_states(id INTEGER PRIMARY KEY, provider TEXT, state TEXT UNIQUE, created_at TEXT, expires_at TEXT);
    CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, severity TEXT, title TEXT, message TEXT, requires_approval INTEGER DEFAULT 1, status TEXT DEFAULT 'OPEN', created_at TEXT, resolved_at TEXT, resolved_by TEXT);
    CREATE TABLE IF NOT EXISTS connections(id INTEGER PRIMARY KEY, provider TEXT UNIQUE, status TEXT DEFAULT 'NOT_CONNECTED', account_label TEXT, auth_url TEXT, last_checked TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS content_outputs(id INTEGER PRIMARY KEY, news_id INTEGER, channel TEXT, format TEXT, status TEXT DEFAULT 'QUEUED', destination TEXT, error TEXT, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS payment_batches(id INTEGER PRIMARY KEY, due_date TEXT, total REAL DEFAULT 0, count INTEGER DEFAULT 0, status TEXT DEFAULT 'DRAFT', approved_by TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS settings_v5(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, updated_by TEXT);
    ''')
    c.execute('INSERT OR IGNORE INTO payroll_rules(id,payment_day,cutoff_day,reminder_days,updated_at,updated_by) VALUES(1,5,28,3,?,?)',(NOW(),'SYSTEM'))
    c.execute("INSERT OR IGNORE INTO election_state(id,active,mode) VALUES(1,0,'NORMAL')")
    for p in ['YouTube','Facebook','Instagram','WhatsApp Business','Payment Gateway','AI Provider','Video Renderer','Voice / TTS','Cloud / Object Storage','SMS / Calling','Live Encoder','LCD Output','IoT Studio Red Light + Buzzer','Physical Studio Gateway']:
        c.execute('INSERT OR IGNORE INTO connections(provider,status) VALUES(?,?)',(p,'NOT_CONNECTED'))
    c.commit(); c.close()
v5_init()

def owner_required(user):
    if user.get('role')!='OWNER': raise HTTPException(403,'Owner approval required')

def v5_audit(user, action, detail=''):
    try: audit(user.get('username','SYSTEM'),action,detail)
    except Exception: pass

def safe_money(v):
    try: return round(float(v),2)
    except Exception: return 0.0

@app.get('/api/v5/overview')
def v5_overview(user=Depends(require_user)):
    c=db();
    q=lambda s: c.execute(s).fetchone()[0]
    rr=c.execute('SELECT * FROM payroll_rules WHERE id=1').fetchone()
    out={'news':q('SELECT COUNT(*) FROM news'),'approved_news':q("SELECT COUNT(*) FROM news WHERE status='APPROVED'"),'hold':q("SELECT COUNT(*) FROM hold_queue WHERE status='HOLD'"),'departments':q("SELECT COUNT(*) FROM departments WHERE enabled=1"),'contributors':q("SELECT COUNT(*) FROM contributors WHERE status='ACTIVE'"),'employees':q("SELECT COUNT(*) FROM employees WHERE active=1"),'referrals':q('SELECT COUNT(*) FROM referrals'),'assets':q("SELECT COUNT(*) FROM brand_assets WHERE active=1"),'open_alerts':q("SELECT COUNT(*) FROM alerts WHERE status='OPEN'"),'outputs_queued':q("SELECT COUNT(*) FROM content_outputs WHERE status IN ('QUEUED','PROCESSING')"),'payroll_rule':dict(rr),'connections':[dict(x) for x in c.execute('SELECT * FROM connections ORDER BY provider')],'onair':dict(c.execute('SELECT * FROM onair WHERE id=1').fetchone())}
    c.close(); return out

@app.post('/connections/{provider}/prepare')
def prepare_connection(provider:str,user=Depends(require_user)):
    owner_required(user); provider=urllib.parse.unquote(provider); supported={'YouTube','Facebook','Instagram','WhatsApp Business'}
    if provider not in supported: raise HTTPException(400,'Unsupported OAuth provider')
    state=secrets.token_urlsafe(32); now=datetime.now(timezone.utc); exp=now+timedelta(minutes=10); c=db(); c.execute('INSERT INTO oauth_states(provider,state,created_at,expires_at) VALUES(?,?,?,?)',(provider,state,now.isoformat(),exp.isoformat())); c.execute('INSERT OR IGNORE INTO connections(provider,status) VALUES(?,?)',(provider,'ACTION_REQUIRED')); c.execute('UPDATE connections SET status=?,last_checked=?,error=NULL WHERE provider=?',('ACTION_REQUIRED',NOW(),provider)); c.commit(); c.close()
    if provider=='YouTube':
        client=os.getenv('GOOGLE_OAUTH_CLIENT_ID','').strip(); redirect=os.getenv('GOOGLE_OAUTH_REDIRECT_URI','').strip()
        if not client or not redirect: return {'provider':provider,'status':'ACTION_REQUIRED','auth_url':None,'message':'Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_REDIRECT_URI in Railway Variables first.'}
        params={'client_id':client,'redirect_uri':redirect,'response_type':'code','access_type':'offline','prompt':'consent','scope':'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly','state':state}; url='https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params)
    else:
        client=os.getenv('META_APP_ID','').strip(); redirect=os.getenv('META_OAUTH_REDIRECT_URI','').strip()
        if not client or not redirect: return {'provider':provider,'status':'ACTION_REQUIRED','auth_url':None,'message':'Set META_APP_ID and META_OAUTH_REDIRECT_URI in Railway Variables first.'}
        params={'client_id':client,'redirect_uri':redirect,'response_type':'code','scope':'pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish,whatsapp_business_management,whatsapp_business_messaging','state':state}; url='https://www.facebook.com/v24.0/dialog/oauth?'+urllib.parse.urlencode(params)
    v5_audit(user,'CONNECTION_OAUTH_PREPARE',provider); return {'provider':provider,'status':'ACTION_REQUIRED','auth_url':url,'message':'Official authorization prepared. CONNECTED is allowed only after a real provider health/publish test.'}

@app.get('/connections/oauth/callback')
def oauth_callback(code:str='',state:str='',error:str='',error_description:str=''):
    if error: return HTMLResponse('<h2>Authorization cancelled</h2><p>'+str(error_description or error)+'</p>')
    c=db(); row=c.execute('SELECT * FROM oauth_states WHERE state=?',(state,)).fetchone()
    if not row: raise HTTPException(400,'Invalid or expired OAuth state')
    if datetime.fromisoformat(row['expires_at'])<datetime.now(timezone.utc): raise HTTPException(400,'OAuth state expired')
    provider=row['provider']; c.execute('UPDATE connections SET status=?,last_checked=?,error=NULL WHERE provider=?',('AUTHORIZED_PENDING_TEST',NOW(),provider)); c.execute('DELETE FROM oauth_states WHERE state=?',(state,)); c.commit(); c.close()
    return HTMLResponse('<h2>KHABAR DHUN — '+provider+'</h2><p>Google/Meta authorization callback received.</p><p>Status: AUTHORIZED_PENDING_TEST</p><p>Return to Master Control and run the real API test before CONNECTED is shown.</p>')

@app.get('/connections/status')
def connections_status(user=Depends(require_user)):
    c=db(); rows=[]
    for r in c.execute('SELECT * FROM connections ORDER BY provider').fetchall():
        status=r['status']
        if status=='CONNECTED' and not r['last_checked']:
            status='ACTION_REQUIRED'
        rows.append({**dict(r),'truth_status':status})
    c.close(); return {'connections':rows,'rule':'CONNECTED is valid only after a real provider test; otherwise use ACTION_REQUIRED/NOT_CONNECTED.'}

@app.post('/connections/{provider}/mark-verified')
def mark_connection(provider:str,verification_token:str=Form(...),user=Depends(require_user)):
    owner_required(user)
    expected=os.getenv('KD_PROVIDER_TEST_TOKEN','')
    if not expected or not secrets.compare_digest(verification_token,expected):
        raise HTTPException(403,'Real provider verification token required; status not changed.')
    c=db(); c.execute('UPDATE connections SET status=?,last_checked=?,error=NULL WHERE provider=?',('CONNECTED',NOW(),provider)); c.commit(); c.close(); v5_audit(user,'CONNECTION_MARKED_CONNECTED',provider)
    return {'provider':provider,'status':'CONNECTED','note':'Provider test token accepted.'}

@app.post('/departments/{department}/job')
def department_job(department:str, payload:str=Form('{}'), user=Depends(require_user)):
    c=db(); c.execute('INSERT INTO dept_jobs(department,input_json,status,attempts,created_at,updated_at) VALUES(?,?,?,?,?,?)',(department,payload,'QUEUED',0,NOW(),NOW())); jid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.commit(); c.close(); v5_audit(user,'DEPARTMENT_JOB_QUEUED',f'{department}:{jid}')
    return {'job_id':jid,'department':department,'status':'QUEUED'}

@app.post('/contributors/register')
def contributor_register(username:str=Form(...),name:str=Form(...),district:str=Form(''),user=Depends(require_user)):
    c=db(); c.execute('INSERT OR IGNORE INTO contributors(username,name,district,created_at) VALUES(?,?,?,?)',(username,name,district,NOW())); c.commit(); c.close(); v5_audit(user,'CONTRIBUTOR_REGISTER',username); return {'status':'ACTIVE','username':username}

@app.post('/contributors/{cid}/submit')
def contributor_submit(cid:int,title:str=Form(...),body:str=Form(...),category:str=Form(...),location:str=Form(''),user=Depends(require_user)):
    c=db(); r=c.execute('SELECT * FROM contributors WHERE id=? AND status="ACTIVE"',(cid,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Contributor not found')
    risk='SENSITIVE' if SENSITIVE.search(title+' '+body) else 'NORMAL'; status='HOLD' if risk=='SENSITIVE' else 'PREPROCESSING'
    cur=c.execute('INSERT INTO news(title,body,category,location,source,risk,status,created_at) VALUES(?,?,?,?,?,?,?,?)',(title,body,category,location,'CUSTOMER_CONTRIBUTOR',risk,status,NOW())); nid=cur.lastrowid
    c.execute('INSERT INTO contributor_submissions(contributor_id,title,body,category,location,status,qc_status,news_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(cid,title,body,category,location,status,'PENDING',nid,NOW())); c.commit(); c.close(); v5_audit(user,'CONTRIBUTOR_SUBMISSION',f'{cid}:{nid}'); return {'news_id':nid,'status':status,'public':False,'note':'Preprocessing/QC/verification/Owner approval required before public publication.'}

@app.post('/referrals/add')
def referral_add(referrer:str=Form(...),referred:str=Form(...),user=Depends(require_user)):
    c=db(); c.execute('INSERT INTO referrals(referrer,referred,created_at) VALUES(?,?,?)',(referrer,referred,NOW())); c.commit(); c.close(); v5_audit(user,'REFERRAL_CREATED',referrer+'->'+referred); return {'status':'PENDING'}

@app.post('/referrals/{rid}/approve')
def referral_approve(rid:int,reward:float=Form(0),user=Depends(require_user)):
    owner_required(user); reward=safe_money(reward); c=db(); r=c.execute('SELECT * FROM referrals WHERE id=?',(rid,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Referral not found')
    c.execute('UPDATE referrals SET status="APPROVED",reward=?,approved_at=? WHERE id=?',(reward,NOW(),rid)); key=r['referrer']; c.execute('INSERT OR IGNORE INTO wallets(owner_type,owner_key) VALUES(?,?)',('REFERRER',key)); c.execute('UPDATE wallets SET pending=pending+?,updated_at=? WHERE owner_type=? AND owner_key=?',(reward,NOW(),'REFERRER',key)); c.execute('INSERT INTO wallet_ledger(owner_type,owner_key,kind,amount,reference,status,created_at) VALUES(?,?,?,?,?,?,?)',('REFERRER',key,'REFERRAL',reward,f'referral:{rid}','PENDING',NOW())); c.commit(); c.close(); v5_audit(user,'REFERRAL_APPROVED',str(rid)); return {'status':'APPROVED','reward':reward}

@app.post('/payroll/rules')
def payroll_rules(payment_day:int=Form(...),cutoff_day:int=Form(28),reminder_days:int=Form(3),user=Depends(require_user)):
    owner_required(user)
    if not 1<=payment_day<=28: raise HTTPException(400,'payment_day must be 1..28')
    c=db(); c.execute('UPDATE payroll_rules SET payment_day=?,cutoff_day=?,reminder_days=?,updated_at=?,updated_by=? WHERE id=1',(payment_day,cutoff_day,reminder_days,NOW(),user['username'])); c.commit(); c.close(); v5_audit(user,'PAYROLL_RULES_UPDATE',f'day={payment_day}'); return {'status':'UPDATED','payment_day':payment_day}

@app.post('/employees/add')
def employee_add(username:str=Form(...),name:str=Form(...),role:str=Form(...),district:str=Form(''),base_salary:float=Form(0),incentive_rate:float=Form(0),user=Depends(require_user)):
    owner_required(user); c=db(); c.execute('INSERT OR REPLACE INTO employees(username,name,role,district,base_salary,incentive_rate,created_at) VALUES(?,?,?,?,?,?,?)',(username,name,role,district,safe_money(base_salary),safe_money(incentive_rate),NOW())); c.commit(); c.close(); v5_audit(user,'EMPLOYEE_ADD',username); return {'status':'ACTIVE','username':username}

@app.post('/payroll/generate')
def payroll_generate(period:str=Form(...),user=Depends(require_user)):
    owner_required(user); c=db(); rule=c.execute('SELECT * FROM payroll_rules WHERE id=1').fetchone(); entries=[]; total=0
    for e in c.execute('SELECT * FROM employees WHERE active=1').fetchall():
        base=safe_money(e['base_salary']); inc=round(base*safe_money(e['incentive_rate'])/100.0,2); bonuses=0; deductions=0; payable=round(base+inc+bonuses-deductions,2); total+=payable
        due=f'{period}-{int(rule["payment_day"]):02d}' if re.match(r'^\d{4}-\d{2}$',period) else period
        cur=c.execute('INSERT INTO payroll_entries(employee_id,period,base_salary,incentives,bonuses,deductions,payable,due_date,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(e['id'],period,base,inc,bonuses,deductions,payable,due,NOW())); entries.append({'id':cur.lastrowid,'employee':e['name'],'payable':payable,'due_date':due})
    c.execute('INSERT INTO payment_batches(due_date,total,count,status,created_at) VALUES(?,?,?,?,?)',(entries[0]['due_date'] if entries else period,total,len(entries),'DRAFT',NOW())); c.commit(); c.close(); v5_audit(user,'PAYROLL_GENERATED',period); return {'period':period,'total':total,'count':len(entries),'entries':entries}

@app.get('/api/payroll')
def payroll_api(user=Depends(require_user)):
    c=db(); rows=[dict(x) for x in c.execute('SELECT p.*,e.name,e.username FROM payroll_entries p JOIN employees e ON e.id=p.employee_id ORDER BY p.id DESC LIMIT 100')]; batches=[dict(x) for x in c.execute('SELECT * FROM payment_batches ORDER BY id DESC LIMIT 20')]; c.close(); return {'entries':rows,'batches':batches}

@app.post('/payroll/{entry_id}/approve-pay')
def payroll_approve_pay(entry_id:int,user=Depends(require_user)):
    owner_required(user); c=db(); e=c.execute('SELECT * FROM payroll_entries WHERE id=?',(entry_id,)).fetchone()
    if not e: c.close(); raise HTTPException(404,'Payroll entry not found')
    acc=c.execute('SELECT * FROM payout_accounts WHERE owner_type="EMPLOYEE" AND owner_key=(SELECT username FROM employees WHERE id=?) AND status="CONNECTED"',(e['employee_id'],)).fetchone()
    if not acc:
        c.execute('UPDATE payroll_entries SET status="ACTION_REQUIRED" WHERE id=?',(entry_id,)); c.commit(); c.close(); return {'status':'ACTION_REQUIRED','message':'Secure payout account is not connected; no money was sent.'}
    # Actual bank/provider API call is intentionally not fabricated.
    c.execute('UPDATE payroll_entries SET status="READY_FOR_PROVIDER" WHERE id=?',(entry_id,)); c.commit(); c.close(); v5_audit(user,'PAYROLL_APPROVED_FOR_PROVIDER',str(entry_id)); return {'status':'READY_FOR_PROVIDER','message':'Approved; provider payout action requires a real connected payout API.'}


@app.post('/assets/upload')
async def asset_upload(name:str=Form(...),kind:str=Form(...),asset:UploadFile=File(...),user=Depends(require_user)):
    owner_required(user); data=await asset.read();
    if len(data)>MAX_MEDIA_MB*1024*1024: raise HTTPException(413,'Asset too large')
    ext=Path(asset.filename or '').suffix.lower()[:10]; stored=f'brand_{uuid.uuid4().hex}{ext}'; dest=MEDIA_DIR/stored; dest.write_bytes(data)
    c=db(); old=c.execute('SELECT MAX(version) v FROM brand_assets WHERE name=?',(name,)).fetchone()['v'] or 0; ver=int(old)+1
    c.execute('INSERT INTO brand_assets(name,kind,path,version,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(name,kind,str(dest),ver,1,NOW(),NOW())); c.commit(); c.close(); v5_audit(user,'BRAND_ASSET_UPLOAD',name); return {'status':'ACTIVE','name':name,'version':ver,'url':'/media/'+stored}

@app.get('/api/assets')
def assets_api(user=Depends(require_user)):
    c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM brand_assets ORDER BY kind,name,version DESC')]; c.close(); return rows

@app.post('/assets/{asset_id}/activate')
def asset_activate(asset_id:int,user=Depends(require_user)):
    owner_required(user); c=db(); a=c.execute('SELECT * FROM brand_assets WHERE id=?',(asset_id,)).fetchone()
    if not a: c.close(); raise HTTPException(404,'Asset not found')
    c.execute('UPDATE brand_assets SET active=0,updated_at=? WHERE kind=?',(NOW(),a['kind']))
    c.execute('UPDATE brand_assets SET active=1,updated_at=? WHERE id=?',(NOW(),asset_id))
    if a['kind'].lower()=='logo': c.execute('UPDATE brand SET logo_path=?,updated_at=? WHERE id=1',('/media/'+Path(a['path']).name,NOW()))
    c.commit(); c.close(); v5_audit(user,'BRAND_ASSET_ACTIVATE',f'id={asset_id};kind={a["kind"]}'); return {'status':'ACTIVE','id':asset_id,'kind':a['kind'],'url':'/media/'+Path(a['path']).name}

@app.post('/assets/{asset_id}/disable')
def asset_disable(asset_id:int,user=Depends(require_user)):
    owner_required(user); c=db(); c.execute('UPDATE brand_assets SET active=0,updated_at=? WHERE id=?',(NOW(),asset_id)); c.commit(); c.close(); v5_audit(user,'BRAND_ASSET_DISABLE',str(asset_id)); return {'status':'DISABLED','id':asset_id}

@app.get('/api/alerts/open')
def alerts_open(user=Depends(require_user)):
    c=db(); rows=[dict(x) for x in c.execute("SELECT * FROM alerts WHERE status='OPEN' ORDER BY id DESC LIMIT 20")]; c.close(); return rows

@app.get('/assets/{asset_id}/download')
def asset_download(asset_id:int,user=Depends(require_user)):
    owner_only(user)
    c=db(); a=c.execute('SELECT * FROM brand_assets WHERE id=?',(asset_id,)).fetchone(); c.close()
    if not a: raise HTTPException(404,'Asset not found')
    path=Path(a['path'])
    if not path.exists(): raise HTTPException(404,'Asset file not found')
    from fastapi.responses import FileResponse
    return FileResponse(str(path), filename=path.name, media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')

@app.post('/emergency/red-alert')
def red_alert(title:str=Form(...),message:str=Form(...),user=Depends(require_user)):
    owner_required(user); c=db(); cur=c.execute('INSERT INTO alerts(severity,title,message,requires_approval,created_at) VALUES(?,?,?,?,?)',('RED',title,message,1,NOW())); aid=cur.lastrowid; c.execute('INSERT INTO output_events(event_type,payload,created_at) VALUES(?,?,?)',('RED_ALERT_TRIGGERED',json.dumps({'alert_id':aid}),NOW())); c.commit(); c.close(); v5_audit(user,'RED_ALERT_TRIGGERED',str(aid)); return {'alert_id':aid,'status':'OPEN','note':'Emergency override is staged; connected broadcast/LCD/IoT devices require real connections.'}

@app.post('/emergency/{alert_id}/resolve')
def red_alert_resolve(alert_id:int,user=Depends(require_user)):
    owner_required(user); c=db(); c.execute('UPDATE alerts SET status="RESOLVED",resolved_at=?,resolved_by=? WHERE id=?',(NOW(),user['username'],alert_id)); c.commit(); c.close(); v5_audit(user,'RED_ALERT_RESOLVED',str(alert_id)); return {'status':'RESOLVED'}


def process_internal_outputs():
    internal={'WEBSITE','APP','EPAPER','LCD'}
    c=db(); rows=c.execute("SELECT id,channel FROM content_outputs WHERE status='QUEUED' ORDER BY id LIMIT 100").fetchall()
    for r in rows:
        if r['channel'] in internal:
            c.execute("UPDATE content_outputs SET status='DELIVERED',updated_at=?,error=NULL WHERE id=?",(NOW(),r['id']))
        else:
            c.execute("UPDATE content_outputs SET status='WAITING_CONNECTION',updated_at=?,error=? WHERE id=?",(NOW(),'External platform connection/authorization required',r['id']))
    c.commit(); c.close()

def output_worker():
    while True:
        try: process_internal_outputs()
        except Exception: pass
        time.sleep(10)

threading.Thread(target=output_worker,name='khabar-dhun-output-worker',daemon=True).start()

@app.get('/api/output-control')
def output_control(user=Depends(require_user)):
    c=db(); rows=[dict(x) for x in c.execute("SELECT o.*,n.title,n.body FROM content_outputs o JOIN news n ON n.id=o.news_id ORDER BY o.id DESC LIMIT 100")]; on=dict(c.execute('SELECT * FROM onair WHERE id=1').fetchone()); media=[dict(x) for x in c.execute('SELECT * FROM news_media ORDER BY id DESC LIMIT 200')]; c.close()
    for r in rows: r['media']=[m for m in media if m['news_id']==r['news_id']]
    current=next((r for r in rows if r.get('id')==on.get('current_output_id')),None)
    return {'onair':on,'current':current,'outputs':rows,'program_output_url':'/program-output','lcd_url':'/lcd','public_site':'/site','public_app':'/app','rule':'Program Output is separate from publishing destinations.'}

@app.post('/outputs/create')
def output_create(news_id:int=Form(...),channel:str=Form(...),format:str=Form(...),destination:str=Form(''),user=Depends(require_user)):
    c=db(); n=c.execute('SELECT * FROM news WHERE id=? AND status="APPROVED"',(news_id,)).fetchone();
    if not n: c.close(); raise HTTPException(400,'Only approved news can enter public output queue')
    cur=c.execute('INSERT INTO content_outputs(news_id,channel,format,destination,created_at,updated_at) VALUES(?,?,?,?,?,?)',(news_id,channel,format,destination,NOW(),NOW())); oid=cur.lastrowid; c.commit(); c.close(); v5_audit(user,'OUTPUT_QUEUED',f'{news_id}:{channel}:{format}'); return {'output_id':oid,'status':'QUEUED'}

@app.get('/api/outputs')
def outputs_api(user=Depends(require_user)):
    c=db(); rows=[dict(x) for x in c.execute('SELECT o.*,n.title FROM content_outputs o JOIN news n ON n.id=o.news_id ORDER BY o.id DESC LIMIT 100')]; c.close(); return rows

@app.post('/outputs/{oid}/complete')
def output_complete(oid:int,user=Depends(require_user)):
    owner_required(user); c=db(); c.execute('UPDATE content_outputs SET status="DELIVERED",updated_at=?,error=NULL WHERE id=?',(NOW(),oid)); c.commit(); c.close(); v5_audit(user,'OUTPUT_DELIVERED',str(oid)); return {'status':'DELIVERED','note':'Use only after actual destination delivery is verified.'}

@app.post('/outputs/{oid}/take')
def output_take(oid:int,user=Depends(require_user)):
    owner_required(user); c=db(); row=c.execute('SELECT o.*,n.title FROM content_outputs o JOIN news n ON n.id=o.news_id WHERE o.id=?',(oid,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Output not found')
    c.execute("UPDATE content_outputs SET status='ON_AIR',updated_at=?,error=NULL WHERE id=?",(NOW(),oid))
    c.execute("UPDATE content_outputs SET status='QUEUED',updated_at=? WHERE status='ON_AIR' AND id<>?",(NOW(),oid))
    c.execute("UPDATE onair SET source='DIGITAL_AI_NEWSROOM',mode='LIVE_PROGRAM',current_output_id=?,updated_at=?,started_at=? WHERE id=1",(oid,NOW(),NOW()))
    c.execute("INSERT INTO output_events(event_type,payload,created_at) VALUES(?,?,?)",('PROGRAM_ON_AIR',json.dumps({'output_id':oid,'title':row['title']},ensure_ascii=False),NOW()))
    c.commit(); c.close(); v5_audit(user,'PROGRAM_ON_AIR',str(oid)); return {'status':'ON_AIR','output_id':oid,'program_output_url':'/program-output'}

@app.post('/outputs/{oid}/advance')
def output_advance(oid:int,user=Depends(require_user)):
    owner_required(user); c=db(); current=c.execute("SELECT * FROM content_outputs WHERE id=?",(oid,)).fetchone()
    if not current: c.close(); raise HTTPException(404,'Output not found')
    nxt=c.execute("SELECT o.* FROM content_outputs o WHERE o.status='QUEUED' AND o.channel='LCD' ORDER BY o.id LIMIT 1").fetchone()
    if not nxt: nxt=c.execute("SELECT o.* FROM content_outputs o WHERE o.status='QUEUED' AND o.channel IN ('WEBSITE','APP') ORDER BY o.id LIMIT 1").fetchone()
    c.execute("UPDATE content_outputs SET status='DELIVERED',updated_at=? WHERE id=? AND status='ON_AIR'",(NOW(),oid))
    if nxt:
        c.execute("UPDATE content_outputs SET status='ON_AIR',updated_at=? WHERE id=?",(NOW(),nxt['id']))
        c.execute("UPDATE onair SET source='DIGITAL_AI_NEWSROOM',mode='LIVE_PROGRAM',current_output_id=?,updated_at=?,started_at=? WHERE id=1",(nxt['id'],NOW(),NOW()))
        result={'status':'ADVANCED','next_output_id':nxt['id']}
    else:
        c.execute("UPDATE onair SET current_output_id=NULL,mode='STANDBY',updated_at=?,started_at=NULL WHERE id=1",(NOW(),))
        result={'status':'STANDBY','next_output_id':None}
    c.commit(); c.close(); v5_audit(user,'PROGRAM_AUTO_ADVANCE',json.dumps(result)); return result

@app.get('/api/program-output')
def program_output_api():
    c=db(); on=c.execute('SELECT * FROM onair WHERE id=1').fetchone(); current=None
    if on and on['current_output_id']: current=c.execute("SELECT o.*,n.title,n.body FROM content_outputs o JOIN news n ON n.id=o.news_id WHERE o.id=?",(on['current_output_id'],)).fetchone()
    if not current: current=c.execute("SELECT o.*,n.title,n.body FROM content_outputs o JOIN news n ON n.id=o.news_id WHERE o.status='ON_AIR' ORDER BY o.updated_at DESC LIMIT 1").fetchone()
    media=[]
    queue=[dict(x) for x in c.execute("SELECT o.*,n.title FROM content_outputs o JOIN news n ON n.id=o.news_id WHERE o.status='QUEUED' ORDER BY o.id LIMIT 10")]
    if current: media=[dict(x) for x in c.execute('SELECT * FROM news_media WHERE news_id=? ORDER BY id DESC',(current['news_id'],))]
    c.close(); return {'onair':dict(on) if on else {},'current':dict(current) if current else None,'media':media,'queue':queue,'server_time':NOW()}

@app.get('/program-output',response_class=HTMLResponse)
def program_output():
    html = r"""<!doctype html><html lang="hi"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KHABAR DHUN — LIVE PROGRAM OUTPUT</title><style>body{margin:0;background:#02060b;color:#fff;font-family:Arial}header{padding:14px 20px;background:#091525;border-bottom:1px solid #263b55}.live{color:#ff314d;font-weight:900}.wrap{max-width:1500px;margin:auto;padding:16px}.screen{background:#000;border:2px solid #263b55;border-radius:14px;overflow:hidden;min-height:55vh;display:flex;align-items:center;justify-content:center}.screen video{width:100%;height:68vh;background:#000;object-fit:contain}.placeholder{text-align:center;padding:40px}.meta,.next{padding:14px;margin-top:12px;background:#0c1725;border:1px solid #263b55;border-radius:12px}.err{color:#ff6577}</style><header><b>KHABAR DHUN</b> · <span class="live">🔴 LIVE PROGRAM VIDEO OUTPUT</span> · <span id="state">CONNECTING…</span></header><main class="wrap"><div class="screen" id="screen"><div class="placeholder">LIVE PROGRAM OUTPUT तैयार हो रहा है…</div></div><div class="meta" id="meta"></div><div class="next" id="next">Program queue monitor active</div></main><script>let lastKey="";let currentId=null;async function advance(id){try{await fetch('/outputs/'+id+'/advance',{method:'POST'});lastKey='';load()}catch(e){}}async function load(){try{const d=await fetch('/api/program-output?ts='+Date.now()).then(r=>r.json());const c=d.current;state.textContent=c?'ON AIR':'WAITING';if(!c){screen.innerHTML='<div class="placeholder"><h1>कोई program item ON AIR नहीं है</h1><p>Master Control से approved output को TAKE LIVE करें.</p></div>';meta.textContent='';next.textContent='Queue: '+((d.queue||[]).map(x=>x.title).join(' → ')||'empty');return}const m=(d.media||[]).find(x=>(x.mime_type||'').startsWith('video/'));const key=c.id+'|'+(m?m.stored_name:'');if(key!==lastKey){if(m){screen.innerHTML='<video id="vid" controls autoplay muted playsinline></video>';const v=document.getElementById('vid');v.src='/media/'+encodeURIComponent(m.stored_name);v.addEventListener('loadedmetadata',()=>{const st=Date.parse((d.onair||{}).started_at||'');if(st&&!isNaN(st)){const elapsed=Math.max(0,(Date.now()-st)/1000);if(elapsed<v.duration-0.5)v.currentTime=Math.min(elapsed,v.duration-0.2)}v.play().catch(()=>{})});v.addEventListener('ended',()=>advance(c.id))}else{screen.innerHTML='<div class="placeholder"><h1>'+esc(c.title)+'</h1><p>'+esc((c.body||'').slice(0,1200))+'</p></div>'}currentId=c.id;lastKey=key}const st=Date.parse((d.onair||{}).started_at||'');const elapsed=st&&!isNaN(st)?Math.max(0,(Date.now()-st)/1000):0;meta.innerHTML='<b>ON AIR:</b> '+esc(c.title)+' · <b>LIVE PROGRAM</b> · '+Math.floor(elapsed)+' sec · '+esc(d.server_time);next.textContent='NEXT: '+((d.queue||[]).map(x=>x.title).join(' → ')||'No queued program')}catch(e){state.innerHTML='<span class="err">OUTPUT ERROR</span>'}}function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}load();setInterval(load,3000)</script></html>"""
    return HTMLResponse(html)

@app.get('/studio-output',response_class=HTMLResponse)
def studio_output(request:Request):
    c=db(); b=dict(c.execute('SELECT * FROM brand WHERE id=1').fetchone()); on=dict(c.execute('SELECT * FROM onair WHERE id=1').fetchone()); conn=c.execute("SELECT * FROM connections WHERE provider IN ('Physical Studio Gateway','LCD Output','Live Encoder','IoT Studio Red Light + Buzzer') ORDER BY provider").fetchall(); row=c.execute("SELECT o.*,n.title,n.body FROM content_outputs o JOIN news n ON n.id=o.news_id WHERE o.status='DELIVERED' ORDER BY o.id DESC LIMIT 1").fetchone(); c.close()
    statuses=''.join('<li>'+str(x['provider'])+': <b>'+str(x['status'])+'</b></li>' for x in conn)
    title=(row['title'] if row else 'No verified program output yet'); body=(row['body'][:1800] if row else 'Waiting for a verified program item.')
    html="""<!doctype html><html lang='hi'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='5'><style>body{margin:0;background:#05090f;color:#eef5ff;font-family:Arial}header{padding:14px;background:#081525;border-bottom:1px solid #233b58}main{max-width:1400px;margin:auto;padding:18px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px}.screen{background:#000;border:2px solid #243a55;border-radius:12px;min-height:520px;padding:28px;display:flex;flex-direction:column;justify-content:center}h1{font-size:clamp(30px,5vw,68px);margin:0 0 20px}p{font-size:clamp(18px,2.5vw,30px);line-height:1.4}.card{background:#0c1827;border:1px solid #233b58;border-radius:12px;padding:18px;margin-bottom:12px}small{opacity:.65}</style><header><b>"""+str(b['name'])+"""</b> · STUDIO PROGRAM OUTPUT · AUTO REFRESH 5s</header><main><div class='grid'><section class='screen'><small>ON-AIR INPUT: """+str(on['source'])+""" · MODE: """+str(on['mode'])+"""</small><h1>"""+str(title)+"""</h1><p>"""+str(body)+"""</p></section><aside><div class='card'><h2>Studio Connections</h2><ul>"""+statuses+"""</ul></div><div class='card'><h2>Physical Studio</h2><p>LCD / Encoder / Red Light / Siren status यहाँ वास्तविक gateway health से आएगा।</p></div><a href='/lcd' style='color:#8fd7ff'>Open LCD-only Output</a></aside></div></main></html>"""
    return HTMLResponse(html)

@app.get('/lcd',response_class=HTMLResponse)
def lcd(request:Request):
    c=db(); b=dict(c.execute('SELECT * FROM brand WHERE id=1').fetchone()); row=c.execute("SELECT o.*,n.title,n.body FROM content_outputs o JOIN news n ON n.id=o.news_id WHERE o.status='DELIVERED' ORDER BY o.id DESC LIMIT 1").fetchone(); on=dict(c.execute('SELECT * FROM onair WHERE id=1').fetchone()); c.close();
    return HTMLResponse(f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="10"><style>body{{margin:0;background:#05080d;color:white;font-family:Arial;display:flex;align-items:center;justify-content:center;height:100vh}}main{{width:90%;max-width:1200px}}h1{{font-size:clamp(28px,5vw,70px)}}p{{font-size:clamp(18px,3vw,34px);line-height:1.35}}small{{opacity:.65}}</style></head><body><main><small>{b['name']} · FINAL AUDIENCE OUTPUT · {on['source']}</small><h1>{(row['title'] if row else 'FINAL OUTPUT READY होने की प्रतीक्षा में')}</h1><p>{(row['body'][:1000] if row else 'No verified delivered output yet.')}</p></main></body></html>''')


# --- KHABAR DHUN LIVE MONITOR WALL ---
LIVE_CHANNELS = [
('Aaj Tak','aajtak','https://www.youtube.com/@aajtak/live'),
('ABP News','ABPNews','https://www.youtube.com/@ABPNews/live'),
('India TV','IndiaTV','https://www.youtube.com/@IndiaTV/live'),
('News18 India','News18India','https://www.youtube.com/@News18India/live'),
('Zee News','zeenews','https://www.youtube.com/@zeenews/live'),
('TV9 Bharatvarsh','TV9Bharatvarsh','https://www.youtube.com/@TV9Bharatvarsh/live'),
('NDTV India','ndtvindia','https://www.youtube.com/@ndtvindia/live'),
('Times Now Navbharat','TimesNowNavbharat','https://www.youtube.com/@TimesNowNavbharat/live'),
('Republic Bharat','RepublicBharat','https://www.youtube.com/@RepublicBharat/live'),
('News24','News24','https://www.youtube.com/@News24/live'),
('CNBC Awaaz','CNBCAwaaz','https://www.youtube.com/@CNBCAwaaz/live'),
('DD News','DDNews','https://www.youtube.com/@DDNews/live')]

@app.get('/api/live-wall')
def live_wall_api(user=Depends(require_user)):
    key=os.getenv('YOUTUBE_API_KEY','').strip(); out=[]
    for name,handle,url in LIVE_CHANNELS:
        item={'name':name,'handle':handle,'channel_url':url,'status':'CONNECTION REQUIRED','video_id':None,'checked_at':NOW()}
        if key:
            try:
                q=urllib.parse.urlencode({'part':'id','forHandle':handle,'key':key})
                with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/channels?'+q,timeout=8) as r: d=json.loads(r.read().decode())
                its=d.get('items',[])
                if not its: item['status']='CHANNEL NOT FOUND'
                else:
                    cid=its[0]['id']; q2=urllib.parse.urlencode({'part':'snippet','channelId':cid,'eventType':'live','type':'video','maxResults':1,'key':key})
                    with urllib.request.urlopen('https://www.googleapis.com/youtube/v3/search?'+q2,timeout=8) as r: li=json.loads(r.read().decode()).get('items',[])
                    if li: item.update(status='LIVE',video_id=li[0]['id']['videoId'])
                    else: item['status']='NO LIVE STREAM NOW'
            except Exception as e: item.update(status='API ERROR',error=str(e)[:180])
        out.append(item)
    return {'checked_at':NOW(),'api_configured':bool(key),'channels':out}

@app.get('/live-wall',response_class=HTMLResponse)
def live_wall(request:Request,user=Depends(require_user)):
    cards=''.join('<article class="tile"><header><b>'+name+'</b><span id="s'+str(i)+'" class="pill">CHECKING</span></header><div class="screen" id="v'+str(i)+'"><span>Checking...</span></div><footer><a href="'+url+'" target="_blank" rel="noopener">Official live page</a></footer></article>' for i,(name,handle,url) in enumerate(LIVE_CHANNELS))
    css='body{margin:0;background:#05080d;color:#eef5ff;font-family:Arial,sans-serif}.top{position:sticky;top:0;z-index:5;background:#091321;border-bottom:1px solid #20334b;padding:12px 16px;display:flex;gap:16px;justify-content:space-between;align-items:center}.wall{padding:12px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.tile{background:#0b121c;border:1px solid #1d3045;border-radius:10px;overflow:hidden}.tile header,.tile footer{padding:8px 10px;background:#0d1723;display:flex;justify-content:space-between;align-items:center}.pill{font-size:10px;padding:4px 7px;border-radius:9px;background:#34465a}.live{background:#b51f2e}.screen{aspect-ratio:16/9;background:#000;display:flex;align-items:center;justify-content:center;color:#71869d}iframe{width:100%;height:100%;border:0}a{color:#79bdff;font-size:11px}button{border:0;border-radius:7px;padding:8px 11px}@media(max-width:1100px){.wall{grid-template-columns:repeat(3,1fr)}}@media(max-width:760px){.wall{grid-template-columns:repeat(2,1fr)}}@media(max-width:480px){.wall{grid-template-columns:1fr}}'
    js="""async function refreshWall(){try{const r=await fetch('/api/live-wall',{cache:'no-store'});const d=await r.json();d.channels.forEach((x,i)=>{const s=document.getElementById('s'+i),v=document.getElementById('v'+i);s.textContent=x.status;s.className='pill '+(x.status==='LIVE'?'live':'');if(x.video_id){const src='https://www.youtube.com/embed/'+x.video_id+'?autoplay=1&mute=1&playsinline=1';if(!v.querySelector('iframe')||!v.querySelector('iframe').src.includes(x.video_id))v.innerHTML='<iframe allow="autoplay;encrypted-media;picture-in-picture" allowfullscreen src="'+src+'"></iframe>';}else v.innerHTML='<span>'+x.status+'</span>';});}catch(e){}}refreshWall();setInterval(refreshWall,60000);"""
    html='<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>KHABAR DHUN - Live Monitor Wall</title><style>'+css+'.note{padding:10px 14px;background:#111d2b;border-bottom:1px solid #20334b;font-size:12px}.key{color:#ffd166}.src{font-size:10px;opacity:.7}</style></head><body><div class="top"><div><b>KHABAR DHUN - LIVE SOURCE MONITOR WALL</b><div style="font-size:11px;opacity:.7">TV + official YouTube live monitoring. No channel is marked LIVE without a real current broadcast response.</div></div><button onclick="refreshWall()">CHECK NOW</button></div><div id="note" class="note">Checking YouTube live discovery…</div><main class="wall">'+cards+'</main><script>'+js.replace("d.channels.forEach((x,i)=>{", "document.getElementById('note').innerHTML=d.api_configured?'YouTube API connected — current live broadcasts are being checked automatically.':'<span class=\"key\">ACTION REQUIRED:</span> Add YOUTUBE_API_KEY to Railway. Until then the wall will show official live-page links, not fake LIVE video.';d.channels.forEach((x,i)=>{")+'</script></body></html>'
    return HTMLResponse(html)

@app.get('/api/live-wall/connection')
def live_wall_connection(user=Depends(require_user)):
    return {
        'provider':'YouTube Data API',
        'status':'CONNECTED' if os.getenv('YOUTUBE_API_KEY','').strip() else 'ACTION_REQUIRED',
        'credential':'YOUTUBE_API_KEY',
        'secret_exposed':False,
        'purpose':'Discover current official channel live broadcasts for the monitoring wall',
        'channels':len(LIVE_CHANNELS),
    }

@app.get('/api/studio-gateway')
def studio_gateway_status(user=Depends(require_user)):
    c=db(); row=c.execute("SELECT * FROM connections WHERE provider='Physical Studio Gateway'").fetchone()
    c.close(); return dict(row) if row else {'provider':'Physical Studio Gateway','status':'NOT_CONNECTED'}

@app.post('/studio-gateway/connect')
def studio_gateway_connect(url:str=Form(...),token_ref:str=Form(''),user=Depends(require_user)):
    owner_required(user); c=db(); c.execute("INSERT OR IGNORE INTO connections(provider,status) VALUES('Physical Studio Gateway','ACTION_REQUIRED')")
    c.execute("UPDATE connections SET status='ACTION_REQUIRED',auth_url=?,last_checked=?,error=NULL WHERE provider='Physical Studio Gateway'",(url,NOW())); c.commit(); c.close(); v5_audit(user,'STUDIO_GATEWAY_CONNECT_PREPARE',url)
    return {'provider':'Physical Studio Gateway','status':'ACTION_REQUIRED','message':'Gateway health verification required; no device is marked connected until /health succeeds.'}

@app.post('/studio-gateway/verify')
def studio_gateway_verify(user=Depends(require_user)):
    owner_required(user); c=db(); row=c.execute("SELECT * FROM connections WHERE provider='Physical Studio Gateway'").fetchone()
    if not row or not row['auth_url']: c.close(); return {'status':'ACTION_REQUIRED','message':'Studio Gateway URL is not configured.'}
    try:
        import urllib.request
        req=urllib.request.Request(row['auth_url'].rstrip('/')+'/health',method='GET')
        with urllib.request.urlopen(req,timeout=5) as r: payload=json.loads(r.read().decode())
        ok=any(d.get('status')=='CONNECTED' for d in payload.get('devices',{}).values())
        status='CONNECTED' if ok else 'ACTION_REQUIRED'
        err=None if ok else 'No configured studio device reported CONNECTED'
        c.execute("UPDATE connections SET status=?,last_checked=?,error=? WHERE provider='Physical Studio Gateway'",(status,NOW(),err)); c.commit(); c.close(); v5_audit(user,'STUDIO_GATEWAY_VERIFY',status); return {'status':status,'gateway':payload}
    except Exception as e:
        c.execute("UPDATE connections SET status='ERROR',last_checked=?,error=? WHERE provider='Physical Studio Gateway'",(NOW(),str(e)[:300])); c.commit(); c.close(); return {'status':'ERROR','error':str(e)[:300]}

@app.post('/settings/central')
def central_setting(key:str=Form(...),value:str=Form(...),user=Depends(require_user)):
    owner_required(user); c=db(); c.execute('INSERT INTO settings_v5(key,value,updated_at,updated_by) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(key,value,NOW(),user['username'])); c.commit(); c.close(); v5_audit(user,'CENTRAL_SETTING_UPDATE',key); return {'status':'UPDATED','key':key,'value':value}
