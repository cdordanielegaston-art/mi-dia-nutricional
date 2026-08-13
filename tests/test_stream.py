# -*- coding: utf-8 -*-
"""Mide la mejora REAL del streaming: cuanto tarda en aparecer ALGO en pantalla
frente a cuanto tarda la respuesta completa."""
import sys, io, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URL = "http://localhost:8793"
CAT = ("des_carb [Desayuno/Carbohidrato]:avena=Avena (40g)|hall30=Harina almendra 30g\n"
       "alm_prot [Almuerzo/Proteina]:pech180a=Pechuga 180g|pech200a=Pechuga 200g")
SYS = ('Sos el asistente nutricional de la app de Gaston. Se breve, rioplatense.\n'
       'Para comidas del catalogo usa seleccionar_opcion; para las de afuera agregar_comida_libre.\n'
       'CATALOGO:\n' + CAT + '\n\nEstado actual del dia: {"kcal":0}')
ESTADO = {"sel": {}, "gasto": "0", "extrasLibres": [], "diaTipico": {},
          "diaTipicoCustom": None, "seccionesPorComida": {}, "memoria": [],
          "resumen": {}, "catalogo": CAT}

def cuerpo(msg, conv):
    return {"message": msg, "model": "claude-haiku-4-5-20251001", "systemPrompt": SYS,
            "convId": conv, "history": [], "state": ESTADO}

def pedir(ruta, msg, conv):
    req = urllib.request.Request(URL + ruta, method="POST",
        data=json.dumps(cuerpo(msg, conv)).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    hitos = {"primer_byte": None, "primera_tool": None, "primer_texto": None, "fin": None}
    texto = ""
    with urllib.request.urlopen(req, timeout=200) as r:
        if ruta == "/chat":
            d = json.loads(r.read().decode("utf-8"))
            hitos["fin"] = time.perf_counter() - t0
            return hitos, d.get("reply", ""), d.get("state", {})
        buf = ""
        while True:
            trozo = r.read1(4096)
            if not trozo:
                break
            if hitos["primer_byte"] is None:
                hitos["primer_byte"] = time.perf_counter() - t0
            buf += trozo.decode("utf-8", "replace")
            partes = buf.split("\n\n")
            buf = partes.pop()
            for p in partes:
                linea = next((l for l in p.split("\n") if l.startswith("data: ")), None)
                if not linea:
                    continue
                ev = json.loads(linea[6:])
                ahora = time.perf_counter() - t0
                if ev["tipo"] == "tool" and hitos["primera_tool"] is None:
                    hitos["primera_tool"] = ahora
                elif ev["tipo"] == "delta":
                    if hitos["primer_texto"] is None:
                        hitos["primer_texto"] = ahora
                elif ev["tipo"] == "texto":
                    texto += ev["texto"]
                    if hitos["primer_texto"] is None:
                        hitos["primer_texto"] = ahora
                elif ev["tipo"] == "fin":
                    hitos["fin"] = ahora
                    return hitos, ev.get("reply", texto), ev.get("state", {})
                elif ev["tipo"] == "error":
                    raise RuntimeError(ev["error"])
    return hitos, texto, {}

print("Precalentando...")
urllib.request.urlopen(urllib.request.Request(URL + "/warmup", method="POST",
    data=json.dumps({"model": "claude-haiku-4-5-20251001", "systemPrompt": SYS,
                     "convId": "t-str"}).encode(),
    headers={"Content-Type": "application/json"}), timeout=30)
time.sleep(9)
print("listo.\n")

PEDIDOS = [
    "poneme pechuga de 200 en el almuerzo",
    "agregame una porcion de pizza",
]

print("=" * 78)
print("STREAMING (/chat/stream)")
print("=" * 78)
for i, msg in enumerate(PEDIDOS, 1):
    h, txt, st = pedir("/chat/stream", msg, "t-str")
    def f(v): return f"{v:.1f}s" if v is not None else "  -  "
    print(f"\n{i}. {msg!r}")
    print(f"   dia actualizado en pantalla : {f(h['primera_tool'])}   <- lo que se VE cambiar")
    print(f"   primer texto visible        : {f(h['primer_texto'])}")
    print(f"   respuesta completa          : {f(h['fin'])}")
    if h["primera_tool"] and h["fin"]:
        print(f"   -> el dia cambio {h['fin'] - h['primera_tool']:.1f}s ANTES de que terminara de hablar")
    print(f"   respuesta: {txt[:80]}")

print("\n" + "=" * 78)
print("SIN STREAMING (/chat) — el mismo pedido, para comparar")
print("=" * 78)
h, txt, st = pedir("/chat", "poneme pechuga de 180 en el almuerzo", "t-str")
print(f"   nada en pantalla hasta : {h['fin']:.1f}s")
print(f"   respuesta: {txt[:80]}")
