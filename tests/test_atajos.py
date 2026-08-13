# -*- coding: utf-8 -*-
"""Prueba los atajos locales contra mensajes REALES para encontrar falsos positivos."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r"D:\Datos Gaston\Desktop\Claude Code\mi_dia_nutricional_pwa")

import mdn_bridge as B

# Estado realista
B._state.update({
    "sel": {"des_carb": "hall30", "des_prot": "huevos2_8"},
    "gasto": "0",
    "extrasLibres": [],
    "diaTipico": {"des_carb": "hall30", "des_prot": "pech200", "alm_prot": "pech180a"},
    "diaTipicoCustom": None,
    "seccionesPorComida": {"desayuno": ["des_"], "almuerzo": ["alm_"], "cena": ["cena_"],
                           "merienda": ["mer_"], "media_manana": ["mm_"]},
    "memoria": [],
    "resumen": {"kcal": 1900, "p": 210, "c": 107, "f": 64},
    "catalogo": "",
    "_cat_lookup": {},
    "_guardar": False,
})

# (mensaje, DEBERIA_ser_atajo)
CASOS = [
    # --- Deberían ser atajo (simples, sin ambigüedad) ---
    ("poneme 2400 de gasto",                      True),
    ("gasto 2800",                                True),
    ("cargame el dia tipico",                     True),
    ("cargá mi día típico",                       True),
    # "como voy" va a Claude A PROPOSITO: merece analisis, no una plantilla fija
    ("como voy",                                  False),
    ("limpiá el día",                             True),

    # --- NO deberían ser atajo (necesitan a Claude) ---
    ("comí un alfajor",                           False),
    ("+ 30 gramos de harina de almendras como comida libre", False),
    ("me comí una pizza grande",                  False),
    ("poné pechuga 200g en el almuerzo",          False),  # ← selección puntual, NO día típico
    ("poneme el desayuno con avena en vez de harina", False),
    ("cargá 2 huevos en la cena",                 False),
    ("¿cómo voy con la proteína?",                False),  # ← pregunta que merece análisis
    ("¿me alcanza la proteína hoy?",              False),
    ("qué me falta para llegar al déficit",       False),
    ("acordate que no como lácteos",              False),
    ("saca el alfajor que agregué",               False),
    ("poneme 2400 de gasto y cargame el desayuno", False),  # ← COMPUESTO
    ("cargame el dia tipico pero sin la cena",    False),   # ← con excepción
    ("gasté 2400 hoy, ¿cuánto déficit tengo?",    False),   # ← gasto + pregunta
    ("cuánta proteína tiene la pechuga",          False),   # ← pregunta de conocimiento
    ("guardá el día y decime cómo me fue",        False),   # ← compuesto
]

print("=" * 78)
print(f"{'MENSAJE':<52} {'ESPERADO':<9} {'REAL':<9} {'OK'}")
print("=" * 78)

fallos = []
for msg, deberia in CASOS:
    # reset sel a estado limpio para no arrastrar
    B._state["sel"] = {"des_carb": "hall30", "des_prot": "huevos2_8"}
    B._state["gasto"] = "0"
    try:
        reply, fue = B._atajo_local(msg)
    except Exception as e:
        reply, fue = f"EXCEPCION: {e}", None
    ok = (fue == deberia)
    marca = "OK" if ok else "<<< FALLA"
    print(f"{msg[:50]:<52} {str(deberia):<9} {str(fue):<9} {marca}")
    if not ok:
        fallos.append((msg, deberia, fue, reply))

print("=" * 78)
print(f"\nFALLAS: {len(fallos)} de {len(CASOS)}\n")
for msg, deberia, fue, reply in fallos:
    tipo = "FALSO POSITIVO (atajo cuando NO debia)" if fue else "no atajo cuando si debia"
    print(f"  [{tipo}]")
    print(f"    msg: {msg}")
    print(f"    respondio: {reply}")
    print()
