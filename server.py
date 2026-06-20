# -*- coding: utf-8 -*-
# Cloud server — deploy this to Railway
from flask import Flask, Response, jsonify, request
import threading, time, uuid, json, os, io, base64
import numpy as np
import cv2

app = Flask(__name__)
rooms = {}
rooms_lock = threading.Lock()


def make_room(name):
    room_id = uuid.uuid4().hex[:6]
    room = {
        'id': room_id, 'name': name,
        'latest_frame': None, 'frame_lock': threading.Lock(),
        'chat_messages': [], 'chat_lock': threading.Lock(),
        'audio_init': None, 'audio_chunks': [],
        'audio_lock': threading.Lock(), 'audio_subscribers': [],
        'audio_mime': 'audio/webm',
        'web_host_last_frame': 0,
        'viewer_count': 0,
    }
    with rooms_lock:
        rooms[room_id] = room
    return room

def get_room(room_id):
    with rooms_lock:
        return rooms.get(room_id)


# ── PWA assets ───────────────────────────────────────────────────────────────
def _make_icon(size):
    try:
        from PIL import Image as PILImage, ImageDraw
        img = PILImage.new('RGB', (size, size), color='#111111')
        draw = ImageDraw.Draw(img)
        cx, cy = size // 2, size // 2
        r = int(size * 0.35)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill='#4a90e2')
        r2 = int(size * 0.22)
        draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill='#1a1a2e')
        r3 = int(size * 0.13)
        draw.ellipse([cx - r3, cy - r3, cx + r3, cy + r3], fill='#4a90e2')
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)
        return buf.read()
    except Exception:
        return base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')

PWA_HEAD = '''<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#4a90e2">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Treasure Hunt">
<link rel="apple-touch-icon" href="/icon-192.png">
<style>
#pwa-install-btn{display:none;position:fixed;bottom:18px;right:18px;z-index:9999;
  background:#4a90e2;color:#fff;border:none;border-radius:24px;padding:10px 20px;
  font-size:15px;font-weight:bold;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,0.4);}
</style>
<script>
let _pwaPrompt=null;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();_pwaPrompt=e;const b=document.getElementById('pwa-install-btn');if(b)b.style.display='block';});
function pwaInstall(){if(_pwaPrompt){_pwaPrompt.prompt();_pwaPrompt.userChoice.then(()=>{_pwaPrompt=null;const b=document.getElementById('pwa-install-btn');if(b)b.style.display='none';});}}
if("serviceWorker"in navigator)navigator.serviceWorker.register("/sw.js");
</script>'''

PWA_INSTALL_BTN = '<button id="pwa-install-btn" onclick="pwaInstall()">📲 Install App</button>'


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/manifest.json')
def pwa_manifest():
    manifest = {
        "name": "Treasure Hunt", "short_name": "TreasureHunt",
        "description": "Live camera streaming with chat",
        "start_url": "/", "display": "standalone",
        "background_color": "#111111", "theme_color": "#4a90e2",
        "orientation": "portrait",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
        ]
    }
    return Response(json.dumps(manifest), mimetype='application/manifest+json')

@app.route('/sw.js')
def service_worker():
    sw = "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(clients.claim()));self.addEventListener('fetch',e=>e.respondWith(fetch(e.request).catch(()=>new Response('Offline',{status:503}))));"
    return Response(sw, mimetype='application/javascript')

@app.route('/icon-192.png')
def icon_192():
    return Response(_make_icon(192), mimetype='image/png')

@app.route('/icon-512.png')
def icon_512():
    return Response(_make_icon(512), mimetype='image/png')

@app.route('/api/create_room', methods=['POST'])
def api_create_room():
    data = request.get_json()
    room = make_room(data.get('name', 'Room'))
    return jsonify({'room_id': room['id']})

@app.route('/')
def lobby():
    with rooms_lock:
        active = list(rooms.values())
    cards = ""
    for r in active:
        cards += f'''
        <div class="card" onclick="location.href='/room/{r["id"]}'">
          <div class="room-name">{r["name"]}</div>
          <div class="viewers">👥 {r["viewer_count"]} watching</div>
        </div>'''
    if not cards:
        cards = '<p class="no-rooms">No live rooms right now.<br>Check back soon!</p>'
    return f'''<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Treasure Hunt</title>
{PWA_HEAD}
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#111; color:#eee; font-family:Arial,sans-serif; min-height:100dvh; }}
#role-screen {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
  min-height:100dvh; gap:20px; padding:30px; }}
#role-screen h1 {{ font-size:26px; text-align:center; }}
#role-screen p {{ color:#aaa; font-size:14px; text-align:center; }}
.role-btn {{ width:100%; max-width:320px; padding:20px; border-radius:16px; border:none;
  font-size:18px; font-weight:bold; cursor:pointer; display:flex; align-items:center;
  gap:14px; transition:opacity .15s; }}
.role-btn:active {{ opacity:.75; }}
.role-seller {{ background:#e8a020; color:#111; }}
.role-buyer  {{ background:#4a90e2; color:#fff; }}
.role-icon {{ font-size:32px; }}
#seller-screen {{ display:none; flex-direction:column; align-items:center; justify-content:center;
  min-height:100dvh; gap:16px; padding:30px; }}
#seller-screen h2 {{ font-size:22px; }}
#seller-screen input {{ width:100%; max-width:320px; padding:14px 16px; border-radius:12px;
  border:2px solid #e8a020; background:#222; color:#fff; font-size:17px; outline:none; text-align:center; }}
#seller-screen button {{ width:100%; max-width:320px; padding:14px; border-radius:12px; border:none;
  background:#e8a020; color:#111; font-size:17px; font-weight:bold; cursor:pointer; }}
#seller-status {{ font-size:13px; color:#aaa; text-align:center; }}
.back-btn {{ background:none; border:none; color:#aaa; font-size:14px; cursor:pointer; margin-top:8px; }}
#buyer-screen {{ display:none; padding:20px; }}
#buyer-screen h1 {{ text-align:center; margin-bottom:16px; font-size:20px; }}
.card {{ background:#1e1e1e; border:1px solid #333; border-radius:12px; padding:20px;
         margin-bottom:14px; cursor:pointer; transition:background .2s; }}
.card:active {{ background:#2a2a2a; }}
.room-name {{ font-size:18px; font-weight:bold; margin-bottom:6px; }}
.viewers {{ font-size:13px; color:#aaa; }}
.no-rooms {{ color:#aaa; text-align:center; margin-top:40px; line-height:1.8; }}
</style></head>
<body>
{PWA_INSTALL_BTN}
<div id="role-screen">
  <h1>🏴‍☠️ Treasure Hunt</h1>
  <p>Choose your role to continue</p>
  <button class="role-btn role-seller" onclick="showSeller()">
    <span class="role-icon">🛍️</span>
    <div><div>I am a Seller</div><div style="font-size:13px;font-weight:normal;opacity:.8">Host a live room</div></div>
  </button>
  <button class="role-btn role-buyer" onclick="showBuyer()">
    <span class="role-icon">👀</span>
    <div><div>I am a Buyer</div><div style="font-size:13px;font-weight:normal;opacity:.8">Browse live rooms</div></div>
  </button>
</div>
<div id="seller-screen">
  <h2>🛍️ Start Your Room</h2>
  <input id="roomNameInput" placeholder="Room name (e.g. My Shop)" maxlength="30" />
  <button onclick="createRoom()">Go Live 🎥</button>
  <div id="seller-status"></div>
  <button class="back-btn" onclick="showRole()">← Back</button>
</div>
<div id="buyer-screen">
  <h1>👀 Live Rooms</h1>
  {cards}
</div>
<script>
function showRole(){{document.getElementById('role-screen').style.display='flex';document.getElementById('seller-screen').style.display='none';document.getElementById('buyer-screen').style.display='none';}}
function showSeller(){{document.getElementById('role-screen').style.display='none';document.getElementById('seller-screen').style.display='flex';document.getElementById('roomNameInput').focus();}}
function showBuyer(){{document.getElementById('role-screen').style.display='none';document.getElementById('buyer-screen').style.display='block';setTimeout(()=>location.reload(),5000);}}
async function createRoom(){{
  const name=document.getElementById('roomNameInput').value.trim();
  if(!name){{document.getElementById('roomNameInput').style.borderColor='#e05';return;}}
  document.getElementById('seller-status').textContent='Creating room...';
  try{{
    const r=await fetch('/api/create_room',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name}})}});
    const d=await r.json();
    location.href='/host-web/'+d.room_id;
  }}catch(e){{document.getElementById('seller-status').textContent='Error: '+e.message;}}
}}
document.getElementById('roomNameInput').addEventListener('keydown',e=>{{if(e.key==='Enter')createRoom();}});
</script>
</body></html>'''

@app.route('/room/<room_id>')
def room_view(room_id):
    room = get_room(room_id)
    if not room:
        return '<h2 style="color:white;text-align:center;margin-top:40px">Room not found.</h2>', 404
    return f'''<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{room["name"]}</title>
{PWA_HEAD}
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#111; color:#eee; font-family:Arial,sans-serif; height:100dvh; overflow:hidden; }}
#splash {{ display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; gap:16px; }}
#splash h2 {{ font-size:20px; }}
#splash input {{ padding:12px 16px; border-radius:10px; border:2px solid #4a90e2; background:#222; color:#fff; font-size:17px; text-align:center; width:240px; outline:none; }}
#splash button {{ padding:12px 40px; border-radius:10px; border:none; background:#4a90e2; color:#fff; font-size:17px; cursor:pointer; font-weight:bold; }}
#main {{ display:none; flex-direction:column; height:100%; }}
#video-wrap {{ height:40vh; min-height:120px; flex-shrink:0; display:flex; align-items:center; justify-content:center; background:#000; overflow:hidden; }}
#video-wrap img {{ max-width:100%; max-height:100%; object-fit:contain; }}
#chat-wrap {{ flex:1; display:flex; flex-direction:column; background:#1e1e1e; border-top:2px solid #333; min-height:0; }}
#top-bar {{ display:flex; align-items:center; gap:8px; padding:6px 10px; background:#2a2a2a; flex-shrink:0; }}
#messages {{ flex:1; overflow-y:auto; padding:8px 10px; font-size:14px; min-height:0; }}
#messages div {{ margin-bottom:4px; }}
.sender {{ font-weight:bold; color:#7eb8f7; }}
.system {{ color:#aaa; font-style:italic; }}
#send-bar {{ display:flex; gap:8px; padding:8px 10px; flex-shrink:0; }}
#send-bar input {{ flex:1; padding:8px 10px; border-radius:8px; border:1px solid #555; background:#333; color:#eee; font-size:15px; }}
#send-bar button {{ padding:8px 16px; border-radius:8px; border:none; background:#4a90e2; color:#fff; font-size:14px; cursor:pointer; }}
</style></head>
<body>
{PWA_INSTALL_BTN}
<div id="splash">
  <h2>Join: {room["name"]}</h2>
  <input id="nameInput" placeholder="Enter your name..." maxlength="20" autofocus />
  <button onclick="joinStream()">Join</button>
</div>
<div id="main">
  <div id="video-wrap"><img src="/video/{room_id}" /></div>
  <div id="chat-wrap">
    <div id="top-bar">
      <span id="viewerLabel"></span>
      <button id="audioBtn" onclick="enableAudio()" style="margin-left:auto;padding:4px 12px;border-radius:6px;border:none;background:#4a90e2;color:#fff;font-size:13px;cursor:pointer;">🔇 Audio</button>
      <audio id="audioEl" style="display:none"></audio>
    </div>
    <div id="messages"></div>
    <div id="send-bar">
      <input id="msg" placeholder="Type a message..." onkeydown="if(event.key===\'Enter\')sendMsg()" />
      <button onclick="sendMsg()">Send</button>
    </div>
  </div>
</div>
<script>
let seen=0,viewerName='';
document.getElementById('nameInput').addEventListener('keydown',e=>{{if(e.key==='Enter')joinStream();}});
function joinStream(){{
  const name=document.getElementById('nameInput').value.trim();
  if(!name){{document.getElementById('nameInput').style.borderColor='#e05';return;}}
  viewerName=name;
  document.getElementById('splash').style.display='none';
  document.getElementById('main').style.display='flex';
  document.getElementById('viewerLabel').textContent='👤 '+name;
  fetch('/viewer_join/{room_id}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name}})}});
  pollChat();
  window.addEventListener('beforeunload',()=>navigator.sendBeacon('/viewer_leave/{room_id}',JSON.stringify({{name:viewerName}})));
}}
function enableAudio(){{
  const a=document.getElementById('audioEl');
  a.src='/audio_stream/{room_id}';a.play().catch(()=>{{}});
  document.getElementById('audioBtn').textContent='🔊 On';
  document.getElementById('audioBtn').style.background='#27ae60';
  document.getElementById('audioBtn').disabled=true;
}}
function sendMsg(){{
  const text=document.getElementById('msg').value.trim();
  if(!text)return;
  document.getElementById('msg').value='';
  fetch('/send/{room_id}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{sender:viewerName,text}})}});
}}
function pollChat(){{
  fetch('/messages/{room_id}').then(r=>r.json()).then(msgs=>{{
    const box=document.getElementById('messages');
    for(let i=seen;i<msgs.length;i++){{
      const d=document.createElement('div');
      const sys=msgs[i].sender.includes('System');
      d.innerHTML=sys?'<span class="system">'+msgs[i].text+'</span>':'<span class="sender">'+msgs[i].sender+':</span> '+msgs[i].text;
      box.appendChild(d);
    }}
    if(msgs.length>seen)box.scrollTop=box.scrollHeight;
    seen=msgs.length;
  }}).catch(()=>{{}});
  setTimeout(pollChat,1000);
}}
</script></body></html>'''

@app.route('/host-web/<room_id>')
def host_web(room_id):
    room = get_room(room_id)
    if not room:
        return 'Room not found', 404
    return f'''<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Host: {room["name"]}</title>
{PWA_HEAD}
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#111; color:#eee; font-family:Arial,sans-serif; display:flex; flex-direction:column; height:100dvh; overflow:hidden; }}
#top {{ padding:8px; background:#1e1e1e; text-align:center; flex-shrink:0; }}
#top button {{ padding:7px 18px; border-radius:8px; border:none; background:#4a90e2; color:#fff; font-size:14px; cursor:pointer; margin:3px; }}
.stop {{ background:#e05 !important; }}
#status {{ font-size:12px; color:#aaa; margin-top:4px; }}
#video-wrap {{ height:35vh; min-height:120px; flex-shrink:0; display:flex; align-items:center; justify-content:center; background:#000; overflow:hidden; }}
video {{ max-width:100%; max-height:100%; object-fit:contain; transform:scaleX(-1); }}
#chat-wrap {{ flex:1; display:flex; flex-direction:column; background:#1e1e1e; border-top:2px solid #333; min-height:0; }}
#messages {{ flex:1; overflow-y:auto; padding:8px 10px; font-size:14px; }}
#messages div {{ margin-bottom:4px; }}
.sender {{ font-weight:bold; color:#f7a97e; }}
.system {{ color:#aaa; font-style:italic; }}
#send-bar {{ display:flex; gap:8px; padding:8px 10px; flex-shrink:0; }}
#send-bar input {{ flex:1; padding:8px 10px; border-radius:8px; border:1px solid #555; background:#333; color:#eee; font-size:15px; }}
#send-bar button {{ padding:8px 16px; border-radius:8px; border:none; background:#4a90e2; color:#fff; font-size:14px; cursor:pointer; }}
</style></head>
<body>
{PWA_INSTALL_BTN}
<div id="top">
  <b style="font-size:15px">{room["name"]}</b>
  <div>
    <button id="startBtn" onclick="startCam()">Start Camera</button>
    <button class="stop" id="stopBtn" onclick="stopCam()" style="display:none">Stop</button>
    <button onclick="flipCam()">Flip</button>
  </div>
  <div id="status">Press Start Camera to begin.</div>
</div>
<div id="video-wrap"><video id="vid" autoplay playsinline muted></video></div>
<div id="chat-wrap">
  <div id="messages"></div>
  <div id="send-bar">
    <input id="msg" placeholder="Message..." onkeydown="if(event.key===\'Enter\')sendMsg()" />
    <button onclick="sendMsg()">Send</button>
  </div>
</div>
<script>
let stream=null,sending=false,canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
let facingMode='environment',seen=0,audioRecorder=null;
async function startCam(){{
  try{{
    stream=await navigator.mediaDevices.getUserMedia({{video:{{facingMode}},audio:false}});
    document.getElementById('vid').srcObject=stream;
    document.getElementById('startBtn').style.display='none';
    document.getElementById('stopBtn').style.display='';
    document.getElementById('status').textContent='Streaming live!';
    sending=true; sendFrames(); startMic();
  }}catch(e){{document.getElementById('status').textContent='Camera error: '+e.message;}}
}}
async function startMic(){{
  try{{
    const ms=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t))||'';
    audioRecorder=new MediaRecorder(ms,mime?{{mimeType:mime}}:{{}});
    audioRecorder.ondataavailable=e=>{{
      if(e.data&&e.data.size>0)fetch('/upload_audio/{room_id}',{{method:'POST',headers:{{'Content-Type':audioRecorder.mimeType||'audio/webm'}},body:e.data}}).catch(()=>{{}});
    }};
    audioRecorder.start(500);
    document.getElementById('status').textContent='Streaming live! Mic on.';
  }}catch(e){{document.getElementById('status').textContent='Streaming live! (mic denied)';}}
}}
function stopCam(){{
  sending=false;
  if(audioRecorder&&audioRecorder.state!=='inactive')audioRecorder.stop();
  audioRecorder=null;
  if(stream)stream.getTracks().forEach(t=>t.stop());
  stream=null;
  document.getElementById('vid').srcObject=null;
  document.getElementById('startBtn').style.display='';
  document.getElementById('stopBtn').style.display='none';
  document.getElementById('status').textContent='Stopped.';
}}
async function flipCam(){{facingMode=facingMode==='user'?'environment':'user';if(stream){{stopCam();await startCam();}}}}
function sendFrames(){{
  if(!sending)return;
  const vid=document.getElementById('vid');
  if(vid.readyState>=2){{
    canvas.width=vid.videoWidth||320;canvas.height=vid.videoHeight||240;
    ctx.drawImage(vid,0,0);
    canvas.toBlob(blob=>{{if(blob)fetch('/upload_frame/{room_id}',{{method:'POST',headers:{{'Content-Type':'image/jpeg'}},body:blob}}).catch(()=>{{}});}}, 'image/jpeg',0.6);
  }}
  setTimeout(sendFrames,100);
}}
function sendMsg(){{
  const text=document.getElementById('msg').value.trim();
  if(!text)return;
  document.getElementById('msg').value='';
  fetch('/send/{room_id}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{sender:'Host',text}})}});
}}
function pollChat(){{
  fetch('/messages/{room_id}').then(r=>r.json()).then(msgs=>{{
    const box=document.getElementById('messages');
    for(let i=seen;i<msgs.length;i++){{
      const d=document.createElement('div');
      const sys=msgs[i].sender.includes('System');
      d.innerHTML=sys?'<span class="system">'+msgs[i].text+'</span>':'<span class="sender">'+msgs[i].sender+':</span> '+msgs[i].text;
      box.appendChild(d);
    }}
    if(msgs.length>seen)box.scrollTop=box.scrollHeight;
    seen=msgs.length;
  }}).catch(()=>{{}});
  setTimeout(pollChat,1000);
}}
pollChat();
</script></body></html>'''

@app.route('/video/<room_id>')
def video_feed(room_id):
    room = get_room(room_id)
    if not room:
        return 'Not found', 404
    def generate():
        while True:
            with room['frame_lock']:
                frame = room['latest_frame']
            if frame is None:
                time.sleep(0.05)
                continue
            _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 40])
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n'
            time.sleep(0.1)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/messages/<room_id>')
def get_messages(room_id):
    room = get_room(room_id)
    if not room:
        return jsonify([])
    with room['chat_lock']:
        return jsonify(room['chat_messages'])

@app.route('/send/<room_id>', methods=['POST'])
def send_message(room_id):
    room = get_room(room_id)
    if not room:
        return jsonify({'ok': False})
    data = request.get_json()
    msg = {'sender': data.get('sender', 'Viewer'), 'text': data.get('text', '')}
    with room['chat_lock']:
        room['chat_messages'].append(msg)
    return jsonify({'ok': True})

@app.route('/upload_frame/<room_id>', methods=['POST'])
def upload_frame(room_id):
    room = get_room(room_id)
    if not room:
        return '', 204
    data = request.data
    if data:
        arr = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            with room['frame_lock']:
                room['latest_frame'] = frame
            room['web_host_last_frame'] = time.time()
    return '', 204

@app.route('/upload_audio/<room_id>', methods=['POST'])
def upload_audio(room_id):
    room = get_room(room_id)
    if not room:
        return '', 204
    chunk = request.data
    if not chunk:
        return '', 204
    mime = request.content_type or 'audio/webm'
    with room['audio_lock']:
        if room['audio_init'] is None:
            room['audio_init'] = chunk
            room['audio_mime'] = mime
        else:
            room['audio_chunks'].append(chunk)
            while len(room['audio_chunks']) > 120:
                room['audio_chunks'].pop(0)
            for q in room['audio_subscribers']:
                try:
                    q.put_nowait(chunk)
                except Exception:
                    pass
    return '', 204

@app.route('/audio_stream/<room_id>')
def audio_stream(room_id):
    room = get_room(room_id)
    if not room:
        return '', 404
    import queue as qmod
    def generate():
        q = qmod.Queue()
        with room['audio_lock']:
            init = room['audio_init']
            buffered = list(room['audio_chunks'][-10:])
            room['audio_subscribers'].append(q)
        try:
            if init:
                yield init
            for chunk in buffered:
                yield chunk
            while True:
                try:
                    yield q.get(timeout=30)
                except qmod.Empty:
                    yield b''
        finally:
            with room['audio_lock']:
                if q in room['audio_subscribers']:
                    room['audio_subscribers'].remove(q)
    return Response(generate(), mimetype=room['audio_mime'])

@app.route('/viewer_join/<room_id>', methods=['POST'])
def viewer_join(room_id):
    room = get_room(room_id)
    if not room:
        return jsonify({'ok': False})
    name = request.get_json().get('name', 'Someone')
    room['viewer_count'] += 1
    with room['chat_lock']:
        room['chat_messages'].append({'sender': '🟢 System', 'text': f'{name} joined'})
    return jsonify({'ok': True})

@app.route('/viewer_leave/<room_id>', methods=['POST'])
def viewer_leave(room_id):
    room = get_room(room_id)
    if not room:
        return jsonify({'ok': False})
    try:
        name = request.get_json(force=True).get('name', 'Someone')
    except Exception:
        name = 'Someone'
    room['viewer_count'] = max(0, room['viewer_count'] - 1)
    with room['chat_lock']:
        room['chat_messages'].append({'sender': '🔴 System', 'text': f'{name} left'})
    return jsonify({'ok': True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
