# -*- coding: utf-8 -*-
"""Conversacion REAL contra el bridge: mide velocidad Y verifica inteligencia.

Ejercita justo lo que se habia roto: correcciones, pedidos compuestos,
seleccion puntual (que el atajo pisaba) y contexto entre mensajes.
"""
import sys, io, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URL = "http://localhost:8793"
CONV = "test-" + str(int(time.time()))

CATALOGO = (
    "des_carb [Desayuno/Carbohidrato]:hall30=Harina almendra 30g|avena=Avena (40g)|des_carb_nada=Sin carbohidrato\n"
    "des_prot [Desayuno/Proteina]:pech200=Pechuga 200g|huevos2_8=2 huevos + 8 claras|des_prot_nada=Nada\n"
    "alm_prot [Almuerzo/Proteina principal]:pech180a=Pechuga 180g|pech200a=Pechuga 200g|pulpa180a=Pulpa vaca 180g|alm_prot_nada=Nada\n"
    "alm_hort [Almuerzo/Hortalizas]:hort250=250g hortalizas|sin_hortalizas=Sin hortalizas\n"
    "cena_prot [Cena/Proteina principal]:pech180c=Pechuga 180g|cena_prot_nada=Nada\n"
)
SYS = (
    'Sos el asistente nutricional dentro de la app "Mi Dia Nutricional" de Gaston. '
    'Se breve, directo, en espanol rioplatense.\n'
    'REGLAS: para comidas del CATALOGO usa seleccionar_opcion con ids EXACTOS. '
    'agregar_comida_libre es SOLO para cosas fuera del catalogo (pizza, alfajor): estima los macros.\n'
    'Si el usuario nombra UNA comida usa cargar_comida_tipica; cargar_dia_tipico es SOLO para el dia entero.\n'
    'CATALOGO:\n' + CATALOGO +
    '\n\nEstado actual del dia: {"kcal":0,"p":0}'
)
ESTADO = {
    "sel": {}, "gasto": "0", "extrasLibres": [],
    "diaTipico": {"des_carb": "hall30", "des_prot": "pech200",
                  "alm_prot": "pech180a", "alm_hort": "hort250", "cena_prot": "pech180c"},
    "diaTipicoCustom": None,
    "seccionesPorComida": {"desayuno": ["des_"], "almuerzo": ["alm_"], "cena": ["cena_"],
                           "merienda": ["mer_"], "media_manana": ["mm_"]},
    "memoria": [], "resumen": {"kcal": 0, "p": 0}, "catalogo": CATALOGO,
}

def post(ruta, payload, timeout=180):
    req = urllib.request.Request(URL + ruta, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")), time.perf_counter() - t

# ── Precalentado, como hace la app al abrir ───────────────────────────────────
print("Precalentando (como cuando abris la app)...")
post("/warmup", {"model": "claude-haiku-4-5-20251001", "systemPrompt": SYS, "convId": CONV})
time.sleep(9)
print("listo.\n")

# (mensaje, que TIENE que pasar, funcion de chequeo sobre el state devuelto)
GUION = [
    ("poneme 2400 de gasto",
     "gasto = 2400",
     lambda s: s["gasto"] == "2400"),

    ("cargame el almuerzo tipico",
     "carga el almuerzo (y NADA del desayuno)",
     lambda s: s["sel"].get("alm_prot") == "pech180a" and "des_carb" not in s["sel"]),

    ("no, pechuga de 200 mejor",                     # <- correccion con contexto
     "cambia SOLO la proteina del almuerzo a 200g",
     lambda s: s["sel"].get("alm_prot") == "pech200a"),

    ("agregame un alfajor",
     "lo suma como comida libre con kcal estimadas",
     lambda s: len(s["extrasLibres"]) == 1 and s["extrasLibres"][0]["kcal"] > 50),

    ("y en el desayuno poneme avena",                # <- seleccion puntual
     "pone avena SIN cargar el desayuno tipico entero",
     lambda s: s["sel"].get("des_carb") == "avena"),

    ("acordate que no tomo leche",
     "lo guarda en memoria",
     lambda s: any("leche" in m.get("texto", "").lower() for m in s["memoria"])),

    ("saca el alfajor",
     "quita la comida libre",
     lambda s: len(s["extrasLibres"]) == 0),
]

print("=" * 86)
print(f"{'#':<3}{'MENSAJE':<36}{'seg':>7}  {'via':<7}{'OK':<4}QUE TENIA QUE PASAR")
print("=" * 86)

tiempos, ok_total = [], 0
for i, (msg, esperado, chequeo) in enumerate(GUION, 1):
    try:
        r, dt = post("/chat", {
            "message": msg, "model": "claude-haiku-4-5-20251001",
            "systemPrompt": SYS, "convId": CONV, "history": [], "state": ESTADO,
        })
    except Exception as e:
        print(f"{i:<3}{msg[:34]:<36}{'---':>7}  ERROR   {e}")
        continue
    st = r.get("state", {})
    # el estado devuelto se arrastra al proximo mensaje, igual que en la app real
    ESTADO["sel"] = st.get("sel", {})
    ESTADO["gasto"] = st.get("gasto", "0")
    ESTADO["extrasLibres"] = st.get("extrasLibres", [])
    ESTADO["memoria"] = st.get("memoria", [])
    try:
        ok = bool(chequeo(st))
    except Exception:
        ok = False
    ok_total += ok
    tiempos.append(dt)
    via = "atajo" if r.get("atajo") else "claude"
    print(f"{i:<3}{msg[:34]:<36}{dt:>6.1f}s  {via:<7}{'OK' if ok else 'MAL':<4}{esperado}")
    if not ok:
        print(f"      respondio: {r.get('reply','')[:72]}")
        print(f"      tools: {r.get('tools')}  sel={json.dumps(st.get('sel',{}))[:90]}")

print("=" * 86)
lentos = [t for t in tiempos if t > 1]
print(f"\nCORRECTOS: {ok_total}/{len(GUION)}")
print(f"Tiempo promedio (los que fueron a Claude): {sum(lentos)/len(lentos):.1f}s" if lentos else "")
print(f"Tiempo maximo: {max(tiempos):.1f}s   ·   minimo: {min(tiempos):.2f}s")
