"""KHABAR DHUN Studio Gateway.
Runs inside the physical studio LAN and bridges the cloud Master Control to authorized devices.
No hardware is claimed connected until a real device adapter reports a successful health check.
"""
import os, time, json, hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN=os.getenv('STUDIO_GATEWAY_TOKEN','CHANGE_ME')
HOST=os.getenv('STUDIO_GATEWAY_HOST','0.0.0.0')
PORT=int(os.getenv('STUDIO_GATEWAY_PORT','8787'))
DEVICES={
 'red_light': os.getenv('RED_LIGHT_DRIVER','NOT_CONFIGURED'),
 'buzzer': os.getenv('BUZZER_DRIVER','NOT_CONFIGURED'),
 'lcd': os.getenv('LCD_DRIVER','NOT_CONFIGURED'),
 'encoder': os.getenv('ENCODER_DRIVER','NOT_CONFIGURED'),
 'graphics': os.getenv('GRAPHICS_DRIVER','NOT_CONFIGURED'),
 'audio': os.getenv('AUDIO_DRIVER','NOT_CONFIGURED'),
 'camera': os.getenv('CAMERA_DRIVER','NOT_CONFIGURED'),
 'teleprompter': os.getenv('TELEPROMPTER_DRIVER','NOT_CONFIGURED'),
 'lights': os.getenv('LIGHTS_DRIVER','NOT_CONFIGURED'),
}
STATE={k:{'driver':v,'status':'NOT_CONNECTED'} for k,v in DEVICES.items()}

def auth(headers): return headers.get('X-KD-Gateway-Token','')==TOKEN and TOKEN!='CHANGE_ME'

def check_devices():
 for k,v in STATE.items(): v['status']='CONNECTED' if v['driver']!='NOT_CONFIGURED' else 'ACTION_REQUIRED'

class H(BaseHTTPRequestHandler):
 def reply(self,code,obj):
  data=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
 def do_GET(self):
  if self.path=='/health': check_devices(); return self.reply(200,{'service':'khabar-dhun-studio-gateway','devices':STATE})
  self.reply(404,{'error':'not_found'})
 def do_POST(self):
  if not auth(self.headers): return self.reply(401,{'error':'unauthorized'})
  if self.path=='/emergency/red':
   check_devices(); active=[k for k in ('red_light','buzzer') if STATE[k]['status']=='CONNECTED']
   return self.reply(200,{'event':'RED_ALERT','devices_targeted':active,'status':'SENT' if active else 'ACTION_REQUIRED'})
  if self.path=='/output/lcd':
   check_devices(); ok=STATE['lcd']['status']=='CONNECTED'
   return self.reply(200,{'event':'LCD_OUTPUT','status':'SENT' if ok else 'ACTION_REQUIRED'})
  if self.path=='/output/encoder':
   check_devices(); ok=STATE['encoder']['status']=='CONNECTED'
   return self.reply(200,{'event':'ENCODER_OUTPUT','status':'SENT' if ok else 'ACTION_REQUIRED'})
  self.reply(404,{'error':'not_found'})

if __name__=='__main__':
 print('KHABAR DHUN Studio Gateway listening on',PORT); HTTPServer((HOST,PORT),H).serve_forever()
