# -*- coding: utf-8 -*-
"""¿El streaming sirve donde la espera DUELE? Respuesta larga y busqueda web."""
import sys, io, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URL = "http://localhost:8793"
CAT = "des_carb [Desayuno/Carbohidrato]:avena=Avena (40g)|hall30=Harina almendra 30g"
SYS = ('Sos el asistente nutricional de Gaston.\n'
       'Para comidas de marca averigua los datos oficiales ANTES de cargar.\n'
       'CATALOGO:\n' + CAT + '\n\nEstado actual del dia: {"kcal":1900,"p":210,"gasto":2400}')
ESTADO = {"sel": {}, "gasto": "2400", "extrasLibres": [], "diaTipico": {},
          "diaTipicoCustom": None, "seccionesPorComida": {}, "memoria": [],
          "resumen": {"kcal": 1900, "p": 210, "c": 107, "f": 64}, "catalogo": CAT}

def correr(msg, conv):
    req = urllib.request.Request(URL + "/chat/stream", method="POST",
        data=json.dumps({"message": msg, "model": "claude-haiku-4-5-20251001",
                         "systemPrompt": SYS, "convId": conv, "history": [],
                         "state": ESTADO}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    primer, deltas, tools, fin, txt = None, 0, [], None, ""
    buf = ""
    with urllib.request.urlopen(req, timeout=250) as r:
        while True:
            trozo = r.read1(4096)
            if not trozo:
                break
            buf += trozo.decode("utf-8", "replace")
            partes = buf.split("\n\n"); buf = partes.pop()
            for p in partes:
                l = next((x for x in p.split("\n") if x.startswith("data: ")), None)
                if not l: continue
                ev = json.loads(l[6:]); ahora = time.perf_counter() - t0
                if ev["tipo"] == "delta":
                    deltas += 1
                    if primer is None: primer = ahora
                elif ev["tipo"] == "tool":
                    tools.append((ev["nombre"], round(ahora, 1)))
                elif ev["tipo"] == "texto":
                    txt += ev["texto"]
                    if primer is None: primer = ahora
                elif ev["tipo"] == "fin":
                    fin = ahora; txt = ev.get("reply", txt)
                elif ev["tipo"] == "error":
                    print("  ERROR:", ev["error"]); return
    print(f"  primer texto en pantalla : {primer:.1f}s" if primer else "  sin texto")
    print(f"  respuesta completa       : {fin:.1f}s")
    if primer and fin:
        print(f"  -> el usuario deja de esperar en blanco {fin - primer:.1f}s antes")
    print(f"  deltas recibidos: {deltas}   tools: {tools}")
    print(f"  largo de la respuesta: {len(txt)} caracteres")
    print(f"  {txt[:150]}")

print("=" * 74)
print("1) RESPUESTA LARGA (analisis, no una confirmacion de una linea)")
print("=" * 74)
correr("hace un analisis detallado de como voy hoy: proteina, deficit, que me falta, "
       "y 3 recomendaciones concretas. Explaya bien cada punto.", "t-largo")

print()
print("=" * 74)
print("2) CON BUSQUEDA WEB (el caso que tardaba 16s)")
print("=" * 74)
correr("cuantas calorias tiene un alfajor jorgito? buscalo", "t-web")
