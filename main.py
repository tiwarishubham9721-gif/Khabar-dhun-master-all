import os, re, sqlite3, json, hashlib, secrets, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

DB=os.getenv('DATABASE_URL','sqlite:////data/khabar_dhun.db').replace('sqlite:///','') or '/data/khabar_dhun.db'
if not DB.startswith('/'): DB='/data/khabar_dhun.db'
SECRET=os.getenv('JWT_SECRET','CHANGE_ME_IN_PRODUCTION')
OWNER=os.getenv('OWNER_USERNAME','owner')
OWNER_PASSWORD=os.getenv('OWNER_PASSWORD','')
templates=Jinja2Templates(directory='app/templates')
app=FastAPI(title='KHABAR DHUN — FINAL MASTER CONTROL', version='3.0.0')
NOW=lambda: datetime.now(timezone.utc).isoformat()

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
    CREATE TABLE IF NOT EXISTS ad_orders(id INTEGER PRIMARY KEY, advertiser TEXT, package TEXT, amount REAL, payment_status TEXT DEFAULT 'PENDING', campaign_status TEXT DEFAULT 'DRAFT', created_at TEXT);
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
    CREATE TABLE IF NOT EXISTS system_settings(key TEXT PRIMARY KEY, value TEXT);
    ''')
    if not c.execute('SELECT id FROM brand WHERE id=1').fetchone(): c.execute('INSERT INTO brand VALUES(1,?,?,?,?,?,?,?)',('KHABAR DHUN','KD','Lagatar chalte khabron ka dhun','KHABAR DHUN','/static/logo.svg','#18a0ff',NOW()))
    if not c.execute('SELECT id FROM onair WHERE id=1').fetchone(): c.execute('INSERT INTO onair VALUES(1,"DIGITAL_BACKUP","NORMAL",?)',(NOW(),))
    if not c.execute('SELECT id FROM security_settings WHERE id=1').fetchone(): c.execute('INSERT INTO security_settings VALUES(1,0,?,?)',(NOW(),'SYSTEM'))
    deps=['News Research','Verification','Breaking News','News Desk','Script Writer','Video Production','Graphics','AI Anchor','Shooting / Camera','Music','Programming / Master Control','Video QC','Social Media','WhatsApp','E-paper','Advertisement','Comments','Analytics','Backup / Operations','Weather','Agriculture / Farmers','Health','Education','Science / Technology','Law / Court','Crime / Investigation','Political Analysis','Elections','Business / Economy','Sports','Entertainment / Cinema / OTT','Auto / Travel','Lifestyle','Human Interest','Fact Check','Ground / Local Reporter','Interviews / Dialogue','Debate / Analysis','Special Coverage','Disaster / Emergency','Photo / Video','Live Reporting','Audience / Comments','Podcast / Audio','International']
    for n in deps: c.execute('INSERT OR IGNORE INTO departments(name,category,created_by,created_at) VALUES(?,?,?,?)',(n,'NEWSROOM','SYSTEM',NOW()))
    for n in ['YouTube','Facebook','Instagram','WhatsApp Business','AI Provider','Video Renderer','Voice / TTS','Payment Gateway','Email','SMS / Calling','Cloud / Object Storage','IoT Studio Red Light + Buzzer']: c.execute('INSERT OR IGNORE INTO services(name,kind) VALUES(?,?)',(n,'EXTERNAL'))
    sources=[('Press Information Bureau','https://pib.gov.in/'),('Election Commission of India','https://www.eci.gov.in/'),('India Meteorological Department','https://mausam.imd.gov.in/'),('Reuters','https://www.reuters.com/'),('The Hindu','https://www.thehindu.com/'),('Indian Express','https://indianexpress.com/'),('Hindustan Times','https://www.hindustantimes.com/'),('NDTV','https://www.ndtv.com/'),('BBC News','https://www.bbc.com/news'),('ANI','https://www.aninews.in/')]
    for n,u in sources: c.execute('INSERT OR IGNORE INTO sources(name,url,status) VALUES(?,?,?)',(n,u,'NOT_CONNECTED'))
    for n in ['YouTube','Facebook','Instagram','WhatsApp Business']: c.execute('INSERT OR IGNORE INTO integrations(name) VALUES(?)',(n,))
    for n in ['Anchor 1','Anchor 2','Anchor 3']: c.execute('INSERT OR IGNORE INTO anchors(name,created_at) VALUES(?,?)',(n,NOW()))
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
    if not OWNER_PASSWORD: return
    c=db(); row=c.execute('SELECT id FROM users WHERE username=?',(OWNER,)).fetchone()
    if not row: c.execute('INSERT INTO users(username,password_hash,role,enabled) VALUES(?,?,?,1)',(OWNER,hash_password(OWNER_PASSWORD),'OWNER')); c.commit()
    c.close()
bootstrap_owner()

def words(text): return set(re.findall(r'[A-Za-z0-9अ-ह]{3,}',(text or '').lower()))
def cluster_key(title): return hashlib.sha1(' '.join(sorted(words(title))).encode()).hexdigest()[:16]

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

def verification_for_news(nid):
    c=db(); n=c.execute('SELECT * FROM news WHERE id=?',(nid,)).fetchone(); rows=c.execute('SELECT ss.*,s.name FROM story_sources ss JOIN sources s ON s.id=ss.source_id WHERE ss.news_id=?',(nid,)).fetchall(); c.close()
    if not n: raise HTTPException(404,'News not found')
    groups={r['independent_group'] or r['name'] for r in rows}; verified=[r for r in rows if r['verified']]; reasons=[]
    if n['risk']=='SENSITIVE' or SENSITIVE.search((n['title'] or '')+' '+(n['body'] or '')): reasons.append('Sensitive story')
    if len(groups)<8: reasons.append('Fewer than 8 independent sources')
    if len(verified)<8: reasons.append('Fewer than 8 verified observations')
    decision='AUTO_ELIGIBLE' if not reasons else 'HOLD'; return {'news_id':nid,'independent_sources':len(groups),'total_sources':len(rows),'verified_observations':len(verified),'confidence':min(.99,len(groups)/8),'decision':decision,'reasons':reasons}

def command_engine(raw,user):
    s=raw.strip(); low=s.lower(); intent='UNKNOWN'; status='PLANNED'; result={}
    c=db()
    if low in {'system health','health check','system status'}:
        intent='SYSTEM_HEALTH'; status='BUILT'; result={'database':'OK','master_control':'AVAILABLE','external_connections':'NOT_VERIFIED'}
    elif re.search(r'(weather|मौसम).*(department|विभाग).*(add|जोड़|जोड़)',low):
        intent='ADD_DEPARTMENT'; status='BUILT'; c.execute('INSERT OR IGNORE INTO departments(name,category,created_by,created_at) VALUES(?,?,?,?)',('Weather','NEWSROOM',user['username'],NOW())); result={'department':'Weather','action':'registered'}
    elif re.search(r'(anchor|एंकर).*(add|जोड़|जोड़)',low):
        intent='ADD_ANCHOR'; status='BUILT'; name='Anchor '+str(c.execute('SELECT COUNT(*) FROM anchors').fetchone()[0]+1); c.execute('INSERT OR IGNORE INTO anchors(name,created_at) VALUES(?,?)',(name,NOW())); result={'anchor':name,'status':'NOT_CONFIGURED'}
    elif re.search(r'(service|सेवा).*(add|जोड़|जोड़)',low):
        intent='ADD_SERVICE'; status='BUILT'; name=s.split(':',1)[1].strip() if ':' in s else 'New Service'; c.execute('INSERT OR IGNORE INTO services(name,kind,created_at) VALUES(?,?,?)',(name,'EXTERNAL',NOW())); result={'service':name,'status':'NOT_CONNECTED'}
    elif 'lockdown' in low:
        owner_only(user); intent='SECURITY_LOCKDOWN'; status='BUILT'; c.execute('UPDATE security_settings SET lockdown=1,updated_at=?,updated_by=? WHERE id=1',(NOW(),user['username'])); result={'lockdown':True}
    elif 'breaking' in low:
        intent='BREAKING_PACKAGE'; status='HOLD'; result={'message':'Breaking package registered; publication still requires verification and policy checks.'}
    else: result={'message':'Safe command registry में यह command उपलब्ध नहीं है. Arbitrary code execution जानबूझकर disabled है.'}
    c.execute('INSERT INTO commands(command,intent,status,result,actor,created_at) VALUES(?,?,?,?,?,?)',(s,intent,status,json.dumps(result,ensure_ascii=False),user['username'],NOW())); c.commit(); c.close(); audit(user['username'],'MASTER_AI_COMMAND',f'{intent}:{status}'); return {'command':s,'intent':intent,'status':status,'result':result}

@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request): return templates.TemplateResponse('login.html',{'request':request})
@app.post('/login')
def login(username:str=Form(...),password:str=Form(...),request:Request=None):
    c=db(); r=c.execute('SELECT * FROM users WHERE username=? AND enabled=1',(username,)).fetchone(); ok=bool(r and verify_password(password,r['password_hash'])); c.close()
    if not ok: log_security(username,'LOGIN_FAILED','invalid credentials','WARN'); raise HTTPException(401,'Invalid login')
    resp=RedirectResponse('/',303); resp.set_cookie('kd_session',token(username),httponly=True,samesite='lax',secure=os.getenv('COOKIE_SECURE','0')=='1'); audit(username,'LOGIN','success'); return resp
@app.get('/logout')
def logout(): r=RedirectResponse('/login',303); r.delete_cookie('kd_session'); return r
@app.get('/',response_class=HTMLResponse)
def home(request:Request,user=Depends(require_user)): return templates.TemplateResponse('control.html',{'request':request,'user':user})
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
    owner_only(user); c=db(); ids=[r['id'] for r in c.execute('SELECT id FROM sources WHERE enabled=1').fetchall()]; c.close(); results=[fetch_rss_source(i) for i in ids]; clusters=rebuild_clusters(); audit(user['username'],'FEED_FETCH_ALL',f'sources={len(ids)}'); return JSONResponse({'results':results,'clusters':clusters[:50],'note':'On-demand fetch only; continuous monitoring requires a deployed scheduler/worker and is NOT VERIFIED.'})
@app.get('/api/clusters')
def api_clusters(user=Depends(require_user)):
    c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM story_clusters ORDER BY updated_at DESC LIMIT 50')]; c.close(); return rows
@app.get('/api/state')
def state(user=Depends(require_user)):
    c=db(); out={'brand':dict(c.execute('SELECT * FROM brand WHERE id=1').fetchone()),'onair':dict(c.execute('SELECT * FROM onair WHERE id=1').fetchone()),'departments':[dict(x) for x in c.execute('SELECT * FROM departments WHERE enabled=1 ORDER BY name')],'anchors':[dict(x) for x in c.execute('SELECT * FROM anchors ORDER BY id')],'sources':[dict(x) for x in c.execute('SELECT * FROM sources ORDER BY name')],'services':[dict(x) for x in c.execute('SELECT * FROM services ORDER BY name')],'news':[dict(x) for x in c.execute('SELECT * FROM news ORDER BY id DESC LIMIT 30')],'hold':[dict(x) for x in c.execute('SELECT * FROM hold_queue WHERE status="HOLD" ORDER BY id DESC LIMIT 30')],'schedules':[dict(x) for x in c.execute('SELECT * FROM schedules ORDER BY start_at LIMIT 30')],'ads':[dict(x) for x in c.execute('SELECT * FROM ads ORDER BY id DESC LIMIT 20')],'integrations':[dict(x) for x in c.execute('SELECT * FROM integrations ORDER BY name')],'security':dict(c.execute('SELECT * FROM security_settings WHERE id=1').fetchone())}; c.close(); return out
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
@app.get('/site',response_class=HTMLResponse)
def public_site(request:Request):
    c=db(); b=dict(c.execute('SELECT * FROM brand WHERE id=1').fetchone()); posts=[dict(x) for x in c.execute('SELECT * FROM news WHERE status="APPROVED" ORDER BY id DESC LIMIT 30')]; c.close(); return templates.TemplateResponse('public_site.html',{'request':request,'brand':b,'posts':posts})
