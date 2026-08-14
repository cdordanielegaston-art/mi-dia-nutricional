# -*- coding: utf-8 -*-
"""¿El chat se pone mas lento a medida que la charla avanza?

El proceso `claude` persiste y acumula TODA la conversacion. Si eso es lo que
explica los 44,8 s de la captura, el mensaje 10 tiene que tardar bastante mas
que el 1. Se mide con un system prompt del tamano real (~10.800 caracteres).
"""
import sys, io, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
URL = "http://localhost:8793"

# Catalogo sintetico del MISMO tamano que el real (6.610 chars, ~30 secciones)
COMIDAS = ["Desayuno", "Media Manana", "Almuerzo", "Merienda", "Cena"]
lineas = []
for ci, comida in enumerate(COMIDAS):
    for si, sec in enumerate(["Carbohidrato", "Proteina", "Hortalizas", "Aceite",
                              "Colores extra", "Energetico"]):
        key = f"s{ci}{si}"
        ops = "|".join(f"{key}_o{k}=Opcion {k} de {sec.lower()} {comida.lower()}"
                       for k in range(9))
        lineas.append(f"{key} [{comida}/{sec}]:{ops}")
CAT = "\n".join(lineas)

SYS = ('Sos el asistente nutricional dentro de la app "Mi Dia Nutricional" de Gaston. '
       'Se breve, directo, en espanol rioplatense. Confirma en una linea lo que hiciste.\n'
       'REGLAS: para comidas del CATALOGO usa seleccionar_opcion con ids EXACTOS.\n'
       'agregar_comida_libre es SOLO para cosas fuera del catalogo.\n'
       'NUNCA uses guardar_dia salvo que te lo pidan explicitamente.\n'
       'CATALOGO:\n' + CAT + '\n\nEstado actual del dia: {"kcal":0,"p":0}')
print(f"system prompt: {len(SYS)} caracteres (~{len(SYS)//3.6:.0f} tokens) — el real son 10.843\n")

ESTADO = {"sel": {}, "gasto": "0", "extrasLibres": [],
          "diaTipico": {f"s{c}{s}": f"s{c}{s}_o1" for c in range(5) for s in range(6)},
          "diaTipicoCustom": None,
          "seccionesPorComida": {"desayuno": ["s0"], "media_manana": ["s1"],
                                 "almuerzo": ["s2"], "merienda": ["s3"], "cena": ["s4"]},
          "memoria": [], "resumen": {"kcal": 0, "p": 0}, "catalogo": CAT}

def pedir(msg, modelo, conv):
    req = urllib.request.Request(URL + "/chat", method="POST",
        data=json.dumps({"message": msg, "model": modelo, "systemPrompt": SYS,
                         "convId": conv, "history": [], "state": ESTADO}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode("utf-8"))
    return time.perf_counter() - t, d

MODELO = "claude-haiku-4-5-20251001"
CONV = "deg-" + str(int(time.time()))

print("Precalentando...")
urllib.request.urlopen(urllib.request.Request(URL + "/warmup", method="POST",
    data=json.dumps({"model": MODELO, "systemPrompt": SYS, "convId": CONV}).encode(),
    headers={"Content-Type": "application/json"}), timeout=30)
time.sleep(10)

# Pedidos que SIEMPRE van a Claude (ningun atajo los agarra)
PEDIDOS = [
    "agregame una pizza chica",
    "cuanta proteina me falta?",
    "agregame un helado",
    "y una gaseosa",
    "cuantas calorias llevo?",
    "agregame un pancho",
    "sacame el helado",
    "que me recomendas para la cena?",
    "agregame un cafe con leche",
    "cuanto deficit tengo?",
]

print("=" * 66)
print(f"{'#':<4}{'seg':>7}   mensaje")
print("=" * 66)
tiempos = []
for i, m in enumerate(PEDIDOS, 1):
    try:
        dt, d = pedir(m, MODELO, CONV)
        tiempos.append(dt)
        print(f"{i:<4}{dt:>6.1f}s   {m}")
    except Exception as e:
        print(f"{i:<4}   ERR   {m}  -> {e}")

print("=" * 66)
if len(tiempos) >= 6:
    ini = sum(tiempos[:3]) / 3
    fin = sum(tiempos[-3:]) / 3
    print(f"\nprimeros 3 (promedio): {ini:.1f}s")
    print(f"ultimos 3  (promedio): {fin:.1f}s")
    print(f"degradacion: {fin/ini:.2f}x  ({fin-ini:+.1f}s por mensaje)")
    print()
    if fin > ini * 1.4:
        print(">>> SI: la charla acumulada lo hace mas lento. Hay que acotar el contexto.")
    else:
        print(">>> NO: no es la charla acumulada. El costo esta en el prompt de base.")
