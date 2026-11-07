"""Bygger den installerbare app (PWA) i mappen docs/.

Kør:  python build_app.py
Læg derefter ændringerne op på GitHub (git add, commit, push). GitHub Pages viser mappen docs/.
På telefonen: åbn adressen og vælg "Føj til hjemmeskærm" (iPhone) / "Installér app" (Android).
"""
import json
import shutil
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "docs"  # GitHub Pages viser mappen docs/
VERSION = "4"  # hæv tallet når appen ændres, så telefonerne henter den nye version

GREEN = (47, 107, 74)
YELLOW = (255, 216, 77)
INK = (29, 42, 34)

HEAD = """<!doctype html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#2f6b4a">
<meta name="description" content="Ugens tilbud, opskrifter og kalorier til Lifesum.">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon-192.png" type="image/png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Tilbudskøkken">
<style>
:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px)}
body{margin:0;font:14px system-ui,sans-serif;-webkit-tap-highlight-color:transparent}
img{max-width:100%}[hidden]{display:none!important}
.install{position:fixed;left:max(12px,env(safe-area-inset-left,0px));right:max(12px,env(safe-area-inset-right,0px));bottom:calc(78px + env(safe-area-inset-bottom,0px));z-index:35;background:var(--ink);color:var(--bg);border-radius:14px;padding:12px 14px;display:flex;gap:12px;align-items:center;max-width:696px;margin:0 auto;box-shadow:0 6px 24px rgb(0 0 0/.25)}
.install p{margin:0;flex:1;font-size:.9rem;min-width:0}
.install button{border:0;border-radius:10px;padding:8px 12px;font-weight:700;background:var(--tag);color:var(--tag-ink)}
.install .no{background:transparent;color:var(--bg);padding:8px}
</style>
</head>
<body>
"""

TAIL = """
<div class="install" id="install" hidden>
  <p id="install-text"></p>
  <button id="install-yes" hidden>Installér</button>
  <button class="no" id="install-no" aria-label="Luk">✕</button>
</div>
<script>
if("serviceWorker" in navigator) addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}));
(function(){
  const standalone=matchMedia("(display-mode: standalone)").matches||navigator.standalone;
  let dismissed=false;try{dismissed=localStorage.getItem("tk-install-no")==="1"}catch(e){}
  if(standalone||dismissed)return;
  const box=document.getElementById("install"),txt=document.getElementById("install-text"),yes=document.getElementById("install-yes");
  const ios=/iphone|ipad|ipod/i.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
  let ev=null;
  addEventListener("beforeinstallprompt",e=>{e.preventDefault();ev=e;txt.textContent="Installér Tilbudskøkkenet på din telefon.";yes.hidden=false;box.hidden=false});
  if(ios){txt.textContent="Installér appen: tryk på Del-knappen i Safari og vælg “Føj til hjemmeskærm”.";box.hidden=false}
  yes.onclick=async()=>{if(!ev)return;ev.prompt();await ev.userChoice;ev=null;box.hidden=true};
  document.getElementById("install-no").onclick=()=>{box.hidden=true;try{localStorage.setItem("tk-install-no","1")}catch(e){}};
  addEventListener("appinstalled",()=>{box.hidden=true});
})();
</script>
</body>
</html>
"""

SW = """const CACHE="tilbudskokken-v__V__";
const SHELL=["./","index.html","manifest.webmanifest","icon-192.png","icon-512.png","apple-touch-icon.png","offers.json"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()))});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener("fetch",e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=="GET")return;
  if(u.origin===location.origin){
    // netværk først (så nye versioner kommer med), cache hvis offline
    e.respondWith(fetch(e.request).then(r=>{const c=r.clone();caches.open(CACHE).then(x=>x.put(e.request,c));return r}).catch(()=>caches.match(e.request).then(r=>r||caches.match("index.html"))));
  }else if(u.hostname.endsWith("fonts.googleapis.com")||u.hostname.endsWith("fonts.gstatic.com")){
    e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(res=>{const c=res.clone();caches.open(CACHE).then(x=>x.put(e.request,c));return res})));
  }
});
"""


def png(path, size, maskable=False):
    """Tegner app-ikonet: grønt felt med et gult prisskilt. Ingen ekstra biblioteker."""
    ss = 4  # supersampling for bløde kanter
    pad = 0.0 if maskable else 0.0
    rad = 0.0 if maskable else 0.22  # afrundede hjørner (iOS runder selv; det skader ikke)

    def inside_bg(x, y):
        if rad == 0:
            return True
        r = rad
        cx = min(max(x, r), 1 - r)
        cy = min(max(y, r), 1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    # prisskilt: rektangel med spids til venstre, drejet -30 grader, med hul
    import math
    ang = math.radians(-30)
    ca, sa = math.cos(ang), math.sin(ang)
    scale = 0.62 if maskable else 0.78

    def tag(x, y):
        # til skiltets koordinater (centrum 0.5,0.5)
        dx, dy = (x - 0.5) / scale, (y - 0.5) / scale
        u = dx * ca + dy * sa
        v = -dx * sa + dy * ca
        if abs(v) > 0.2:
            return 0
        if u > 0.38 or u < -0.38:
            return 0
        if u < -0.18 and abs(v) > (u + 0.38) * 1.0:
            return 0  # spidsen
        if (u + 0.2) ** 2 + v ** 2 < 0.045 ** 2:
            return 0  # hullet
        if 0.02 < u < 0.27 and abs(v) < 0.025:
            return 2  # streg (prisen)
        if 0.02 < u < 0.17 and abs(v - 0.085) < 0.022:
            return 2
        if 0.02 < u < 0.17 and abs(v + 0.085) < 0.022:
            return 2
        return 1

    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) / size
                    y = (py + (sy + 0.5) / ss) / size
                    if not inside_bg(x, y):
                        continue
                    t = tag(x, y)
                    col = GREEN if t == 0 else YELLOW if t == 1 else INK
                    acc[0] += col[0]; acc[1] += col[1]; acc[2] += col[2]; acc[3] += 255
            n = ss * ss
            a = acc[3] / n
            if a:
                k = acc[3] / 255
                row += bytes([round(acc[0] / k), round(acc[1] / k), round(acc[2] / k), round(a)])
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) \
        + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    path.write_bytes(data)


def main():
    OUT.mkdir(exist_ok=True)
    page = (ROOT / "index.html").read_text(encoding="utf-8")
    (OUT / "index.html").write_text(HEAD + page + TAIL, encoding="utf-8")
    shutil.copy(ROOT / "offers.json", OUT / "offers.json")
    (OUT / "sw.js").write_text(SW.replace("__V__", VERSION), encoding="utf-8")
    manifest = {
        "name": "Tilbudskøkkenet", "short_name": "Tilbudskøkken", "lang": "da",
        "description": "Ugens tilbud, opskrifter og kalorier til Lifesum.",
        "start_url": "./", "scope": "./", "display": "standalone", "orientation": "portrait",
        "background_color": "#f3f5ef", "theme_color": "#2f6b4a",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    (OUT / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, size, mask in [("icon-192.png", 192, False), ("icon-512.png", 512, False),
                             ("apple-touch-icon.png", 180, True), ("icon-maskable-512.png", 512, True)]:
        png(OUT / name, size, mask)
        print("ikon", name)
    print("Færdig: appen ligger i", OUT)


if __name__ == "__main__":
    main()
