# -*- coding: utf-8 -*-
"""El pedido EXACTO de la captura (44,2 s con 5 tools, dos de ellas indebidas).

Tiene que: NO guardar el dia, hacer menos herramientas, y tardar bastante menos.
Y el control opuesto: cuando SI se pide guardar, tiene que guardar.
"""
import sys, io, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
URL = "http://localhost:8793"

CAT = ("des_carb [Desayuno/Carbohidrato]:harina_almendra=Harina almendra 30g|avena=Avena (40g)|sin_carb_des=Sin carbohidrato\n"
       "des_prot [Desayuno/Proteina]:huevos2_8=2 huevos + 8 claras|pech200=Pechuga 200g|sin_prot_des=Nada\n"
       "mm_snack [Media Manana/Snack]:almendras_fruta=10 almendras + 1 fruta|alm20g_fruta=20g almendras + 1 fruta|alm20g_sola=20g almendras solas|solo_fruta=Solo 1 fruta|sin_mm=Nada\n"
       "alm_prot [Almuerzo/Proteina principal]:pech180a=Pechuga 180g|sin_prot_alm=Nada")
SYS = ('Sos el asistente nutricional dentro de la app "Mi Dia Nutricional" de Gaston. '
       'Se breve, directo, en espanol rioplatense. Confirma en UNA linea lo que hiciste.\n'
       'Para comidas del CATALOGO usa seleccionar_opcion con ids EXACTOS. '
       'agregar_comida_libre es SOLO para cosas fuera del catalogo.\n'
       'Si el usuario nombra UNA comida usa cargar_comida_tipica.\n'
       'NUNCA uses guardar_dia salvo que te lo pidan explicitamente.\n'
       'CATALOGO:\n' + CAT + '\n\nEstado actual del dia: {"kcal":0,"p":0}')
ESTADO = {"sel": {}, "gasto": "0", "extrasLibres": [],
          "diaTipico": {"des_carb": "harina_almendra", "des_prot": "huevos2_8",
                        "mm_snack": "almendras_fruta", "alm_prot": "pech180a"},
          "diaTipicoCustom": None,
          "seccionesPorComida": {"desayuno": ["des_"], "media_manana": ["mm_"],
                                 "almuerzo": ["alm_"], "cena": ["cena_"], "merienda": ["mer_"]},
          "memoria": [], "resumen": {"kcal": 0, "p": 0}, "catalogo": CAT}

def correr(msg, modelo, conv):
    req = urllib.request.Request(URL + "/chat/stream", method="POST",
        data=json.dumps({"message": msg, "model": modelo, "systemPrompt": SYS,
                         "convId": conv, "history": [], "state": ESTADO}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter(); tools=[]; fin=None; reply=""; st={}
    buf=""
    with urllib.request.urlopen(req, timeout=300) as r:
        while True:
            tr = r.read1(4096)
            if not tr: break
            buf += tr.decode("utf-8","replace")
            ps = buf.split("\n\n"); buf = ps.pop()
            for p in ps:
                l = next((x for x in p.split("\n") if x.startswith("data: ")), None)
                if not l: continue
                ev = json.loads(l[6:])
                if ev["tipo"]=="tool": tools.append(ev["nombre"])
                elif ev["tipo"]=="fin": fin=time.perf_counter()-t0; reply=ev.get("reply",""); st=ev.get("state",{})
                elif ev["tipo"]=="error": print("  ERROR:",ev["error"]); return None
    return fin, tools, reply, st

# ⚠️ El ";" final SIGNIFICA GUARDAR (convencion de Gaston, dicha el 2026-08-14).
# La primera version de este test daba por sentado que guardar ahi estaba MAL — estaba
# mal la suposicion, no el modelo. Lo que si sobraba era agregar_comida_libre
# duplicando la fruta que seleccionar_opcion ya habia puesto.
MSG_CAPTURA = "700, desayuno típico, media mañana: 20 almendras y 1 fruta (manzana);"
MSG_SIN_PUNTOYCOMA = "poneme 1900 de gasto y cargame el almuerzo típico"
MODELO = "claude-sonnet-4-6"
conv = f"gate-{int(time.time())}"

print("Precalentando Sonnet...")
urllib.request.urlopen(urllib.request.Request(URL+"/warmup", method="POST",
    data=json.dumps({"model":MODELO,"systemPrompt":SYS,"convId":conv}).encode(),
    headers={"Content-Type":"application/json"}), timeout=30)
time.sleep(11)

print("=" * 74)
print("EL PEDIDO DE LA CAPTURA (antes: 44,2 s, 5 tools, la fruta duplicada)")
print("=" * 74)
r = correr(MSG_CAPTURA, MODELO, conv)
if r:
    fin, tools, reply, st = r
    print(f"  TIEMPO: {fin:.1f}s      (antes 44,2s)")
    print(f"  herramientas del modelo: {tools}      (antes 5)")
    print(f"  guardo por el ';'?: {'SI — correcto' if st.get('guardar') else 'NO — SE ROMPIO LA CONVENCION'}")
    dup = len(st.get('extrasLibres', []))
    print(f"  duplico la fruta como comida libre?: {'SI — MAL' if dup else 'no — correcto'}")
    print(f"  respuesta: {reply[:150]!r}")
    print(f"  gasto={st.get('gasto')}  secciones cargadas={len(st.get('sel',{}))}")

print()
print("=" * 74)
print("SIN ';' NI PEDIDO DE GUARDAR — el gate tiene que impedir que archive")
print("=" * 74)
r = correr(MSG_SIN_PUNTOYCOMA, MODELO, conv)
if r:
    fin, tools, reply, st = r
    print(f"  TIEMPO: {fin:.1f}s")
    print(f"  herramientas del modelo: {tools}")
    print(f"  guardo?: {'SI — MAL, archivo sin que se lo pidieran' if st.get('guardar') else 'NO — correcto'}")
    print(f"  gasto={st.get('gasto')}  secciones={len(st.get('sel',{}))}")

print()
print("=" * 74)
print("CONTROL: cuando SI se pide guardar, tiene que guardar")
print("=" * 74)
r = correr("ahora si, guarda el dia", MODELO, conv)
if r:
    fin, tools, reply, st = r
    print(f"  TIEMPO: {fin:.1f}s")
    print(f"  herramientas: {tools}")
    print(f"  guardo?: {'SI — correcto' if st.get('guardar') else 'NO — EL GATE QUEDO DEMASIADO DURO'}")
    print(f"  respuesta: {reply[:120]!r}")
