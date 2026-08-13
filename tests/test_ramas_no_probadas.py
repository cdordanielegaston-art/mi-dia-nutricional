# -*- coding: utf-8 -*-
"""Ejercita las ramas que ESCRIBI y NUNCA VI CORRER.

Verde no es probado: hay que provocar la falla y mirar correr la reparacion.
  A) Sonnet — ¿el id 'claude-sonnet-4-6' existe? (nunca se uso)
  B) Imagenes por el payload REAL del front (solo probe el SDK pelado)
  C) Matar el proceso `claude` a mano -> ¿el reintento lo rearma solo?
"""
import sys, io, json, time, base64, zlib, subprocess
from struct import pack
import urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URL = "http://localhost:8793"
SYS = ('Sos el asistente nutricional de la app de Gaston. Se breve.\n'
       'CATALOGO:\ndes_carb [Desayuno/Carbohidrato]:avena=Avena (40g)|hall30=Harina almendra 30g\n'
       '\n\nEstado actual del dia: {"kcal":0}')
ESTADO = {"sel": {}, "gasto": "0", "extrasLibres": [], "diaTipico": {},
          "diaTipicoCustom": None, "seccionesPorComida": {}, "memoria": [],
          "resumen": {}, "catalogo": "des_carb [Desayuno/Carbohidrato]:avena=Avena (40g)"}

def post(ruta, payload, timeout=200):
    req = urllib.request.Request(URL + ruta, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), time.perf_counter() - t, None
    except urllib.error.HTTPError as e:
        return None, time.perf_counter() - t, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return None, time.perf_counter() - t, f"{type(e).__name__}: {e}"

def pid_claude_del_bridge():
    """PID del claude.exe que spawneo el SDK (el _bundled)."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
         "Where-Object { $_.CommandLine -like '*_bundled*' } | "
         "Select-Object -First 1 -ExpandProperty ProcessId"],
        capture_output=True, text=True, timeout=30)
    s = (out.stdout or "").strip()
    return int(s) if s.isdigit() else None

print("=" * 76)
print("A) SONNET — el id 'claude-sonnet-4-6' nunca se probo")
print("=" * 76)
r, dt, err = post("/chat", {"message": "decime solo OK", "model": "claude-sonnet-4-6",
                            "systemPrompt": SYS, "convId": "t-sonnet", "state": ESTADO})
if err:
    print(f"  FALLA ({dt:.1f}s): {err}")
    print("  -> el modelo del selector NO sirve; hay que corregir BRIDGE_MODELS")
else:
    print(f"  OK ({dt:.1f}s): {r.get('reply','')[:90]}")

print()
print("=" * 76)
print("B) IMAGENES — con el payload REAL del front (campo 'images')")
print("=" * 76)
# PNG chico: rectangulo negro sobre blanco
W, H = 140, 44
px = [[255] * (W * 3) for _ in range(H)]
for y in range(14, 30):
    for x in range(12, 120):
        for c in range(3):
            px[y][x * 3 + c] = 0
raw = b"".join(b"\x00" + bytes(f) for f in px)
def ch(t, d):
    c = pack(">I", len(d)) + t + d
    return c + pack(">I", zlib.crc32(t + d) & 0xffffffff)
png = (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
       + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))
b64 = base64.b64encode(png).decode()

r, dt, err = post("/chat", {
    "message": "que ves en la imagen? descripcion breve",
    "model": "claude-haiku-4-5-20251001", "systemPrompt": SYS,
    "convId": "t-img", "state": ESTADO,
    "images": [{"media": "image/png", "b64": b64}],   # <- tal cual lo manda runBridge
})
if err:
    print(f"  FALLA ({dt:.1f}s): {err}")
else:
    txt = r.get("reply", "")
    vio = any(p in txt.lower() for p in ("negro", "rectangul", "barra", "linea", "franja", "blanco"))
    print(f"  respondio ({dt:.1f}s): {txt[:130]}")
    print(f"  -> {'VE la imagen' if vio else 'DUDOSO: no parece describir la imagen'}")

print()
print("=" * 76)
print("C) EL PROCESO SE MUERE — ¿el reintento lo rearma solo?")
print("=" * 76)
pid = pid_claude_del_bridge()
print(f"  proceso claude del bridge: PID {pid}")
if not pid:
    print("  no lo encontre; saltando")
else:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Stop-Process -Id {pid} -Force -Confirm:$false"],
                   capture_output=True, timeout=30)
    print(f"  MATADO el PID {pid}. Mandando un pedido nuevo...")
    r, dt, err = post("/chat", {"message": "decime solo LISTO",
                                "model": "claude-haiku-4-5-20251001", "systemPrompt": SYS,
                                "convId": "t-muerte", "state": ESTADO})
    if err:
        print(f"  FALLA ({dt:.1f}s): {err}")
        print("  -> la app queda ROTA hasta reiniciar el bridge a mano")
    else:
        pid2 = pid_claude_del_bridge()
        print(f"  OK ({dt:.1f}s): {r.get('reply','')[:70]}")
        print(f"  proceso nuevo: PID {pid2}  -> se recupero SOLO")
