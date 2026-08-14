# -*- coding: utf-8 -*-
"""El patron con que Gaston carga el dia: lista separada por comas terminada en ";".

El ";" final significa GUARDAR (convencion suya, 2026-08-14).
Se resuelve local todo lo reconocible y al modelo le queda solo el resto.
"""
import sys, io, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
URL = "http://localhost:8793"

CAT = ("des_carb [Desayuno/Carbohidrato]:harina_almendra=Harina almendra 30g|avena=Avena (40g)|sin_carb_des=Sin carbohidrato\n"
       "des_prot [Desayuno/Proteina]:huevos2_8=2 huevos + 8 claras|pech200=Pechuga 200g|sin_prot_des=Nada\n"
       "mm_snack [Media Manana/Snack]:almendras_fruta=10 almendras + 1 fruta|alm20g_fruta=20g almendras + 1 fruta|alm20g_sola=20g almendras solas|solo_fruta=Solo 1 fruta|sin_mm=Nada\n"
       "alm_prot [Almuerzo/Proteina principal]:pech180a=Pechuga 180g|sin_prot_alm=Nada\n"
       "cena_prot [Cena/Proteina principal]:pech180c=Pechuga 180g|sin_prot_cena=Nada")
SYS = ('Sos el asistente nutricional de la app de Gaston. Se breve, rioplatense.\n'
       'Para comidas del CATALOGO usa seleccionar_opcion con ids EXACTOS.\n'
       'Si el usuario nombra UNA comida usa cargar_comida_tipica.\n'
       'NUNCA uses guardar_dia salvo que te lo pidan.\n'
       'CATALOGO:\n' + CAT + '\n\nEstado actual del dia: {"kcal":0}')
BASE = {"sel": {}, "gasto": "0", "extrasLibres": [],
        "diaTipico": {"des_carb": "harina_almendra", "des_prot": "huevos2_8",
                      "mm_snack": "almendras_fruta", "alm_prot": "pech180a", "cena_prot": "pech180c"},
        "diaTipicoCustom": None,
        "seccionesPorComida": {"desayuno": ["des_"], "media_manana": ["mm_"],
                               "almuerzo": ["alm_"], "cena": ["cena_"], "merienda": ["mer_"]},
        "memoria": [], "resumen": {"kcal": 0}, "catalogo": CAT}

def correr(msg, conv, modelo="claude-sonnet-4-6"):
    req = urllib.request.Request(URL + "/chat/stream", method="POST",
        data=json.dumps({"message": msg, "model": modelo, "systemPrompt": SYS,
                         "convId": conv, "history": [], "state": dict(BASE)}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0=time.perf_counter(); tools=[]; fin=None; reply=""; st={}; atajo=None
    buf=""
    with urllib.request.urlopen(req, timeout=300) as r:
        while True:
            tr=r.read1(4096)
            if not tr: break
            buf+=tr.decode("utf-8","replace")
            ps=buf.split("\n\n"); buf=ps.pop()
            for p in ps:
                l=next((x for x in p.split("\n") if x.startswith("data: ")),None)
                if not l: continue
                ev=json.loads(l[6:])
                if ev["tipo"]=="tool": tools.append(ev["nombre"])
                elif ev["tipo"]=="fin":
                    fin=time.perf_counter()-t0; reply=ev.get("reply",""); st=ev.get("state",{}); atajo=ev.get("atajo")
                elif ev["tipo"]=="error": print("  ERROR:",ev["error"]); return None
    return fin, tools, reply, st, atajo

conv = f"comp-{int(time.time())}"
print("Precalentando...")
urllib.request.urlopen(urllib.request.Request(URL+"/warmup", method="POST",
    data=json.dumps({"model":"claude-sonnet-4-6","systemPrompt":SYS,"convId":conv}).encode(),
    headers={"Content-Type":"application/json"}), timeout=30)
time.sleep(11)

CASOS = [
    # (mensaje, que tiene que pasar)
    ("700, desayuno típico, media mañana: 20 almendras y 1 fruta (manzana);",
     "gasto+desayuno local, media manana al modelo, y GUARDA por el ';'"),
    ("2400, desayuno típico, almuerzo típico, cena típica;",
     "TODO local: 0 llamadas al modelo, y guarda"),
    ("2400, desayuno típico, almuerzo típico",
     "todo local pero SIN ';' -> NO guarda"),
]

print("=" * 78)
for msg, esperado in CASOS:
    r = correr(msg, conv)
    if not r:
        continue
    fin, tools, reply, st, atajo = r
    print(f"\n{msg}")
    print(f"  esperado: {esperado}")
    print(f"  TIEMPO: {fin:.2f}s     {'(sin tocar el modelo)' if atajo else '(paso por el modelo)'}")
    print(f"  herramientas del modelo: {tools or '(ninguna)'}")
    print(f"  guardo: {'SI' if st.get('guardar') else 'no'}   gasto={st.get('gasto')}   "
          f"secciones={len(st.get('sel',{}))}")
    print(f"  respuesta: {reply[:110]!r}")
print()
print("=" * 78)
