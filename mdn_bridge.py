# -*- coding: utf-8 -*-
r"""
MDN BRIDGE -- backend que conecta Mi Dia Nutricional con la suscripcion Claude Max.

La app (HTML/PWA) no puede usar el Agent SDK directo porque corre en el navegador.
Este proceso corre en la PC, expone HTTP en el puerto 8792, y la app le pega a el
en vez de a api.anthropic.com. Tailscale lo hace accesible desde el celular.

Patron obligatorio del MAX BRIDGE (ver apps ECD\MAX BRIDGE\CLAUDE.md):
  1. Scrub de env vars ANTES de importar el SDK
  2. Preflight: exigir authMethod in {claude.ai, oauth_token}
  3. Assert anti-facturacion: apiKeySource in FACTURABLES -> abortar

Uso:
  python mdn_bridge.py          # arranca en 0.0.0.0:8792
  python mdn_bridge.py --port 9000

Consumo: ~0 CPU en reposo (event-driven), ~30 MB RAM.
"""

# ── PASO 1: scrub ANTES de cualquier import del SDK ──────────────────────────
import os
_AUTH_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
              "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
for _v in _AUTH_VARS:
    os.environ.pop(_v, None)

import sys
import json
import shutil
import asyncio
import logging
import argparse
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from threading import Lock

# pythonw no tiene stderr/stdout → redirigir ANTES de que logging los toque
AQUI = Path(__file__).resolve().parent
LOG_DIR = AQUI / "logs"
LOG_DIR.mkdir(exist_ok=True)
if sys.executable.lower().endswith("pythonw.exe") or sys.stderr is None:
    _fallback = open(LOG_DIR / f"bridge_{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8")
    sys.stderr = _fallback
    sys.stdout = _fallback

# ── Silenciar consolas de hijos (el SDK spawnea el CLI) ──────────────────────
if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
    _orig_popen_init = subprocess.Popen.__init__
    def _popen_sin_consola(self, *a, **kw):
        kw["creationflags"] = kw.get("creationflags", 0) | _CREATE_NO_WINDOW
        return _orig_popen_init(self, *a, **kw)
    subprocess.Popen.__init__ = _popen_sin_consola

from flask import Flask, request as flask_request, jsonify, send_from_directory
from flask_cors import CORS

PORT = 8793
FACTURABLES = ("user", "project", "org", "temporary")

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / f"bridge_{datetime.now():%Y-%m-%d}.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("mdn_bridge")


# ═══════════════════════════════════════════════════════════════════════════════
# PASO 2: preflight — ¿el CLI está y está logueado con la suscripción?
# ═══════════════════════════════════════════════════════════════════════════════

def preflight():
    exe = shutil.which("claude")
    if not exe:
        return False, "no encuentro el CLI `claude` en el PATH"
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True,
                           timeout=30, shell=True)
    except Exception as e:
        return False, f"fallo `claude auth status`: {e}"
    raw = (r.stdout or r.stderr or "").strip()
    try:
        st = json.loads(raw)
    except Exception:
        return False, f"no pude parsear la salida: {raw[:200]}"
    if not st.get("loggedIn"):
        return False, "el CLI no está logueado (correr: claude auth login)"
    metodo = st.get("authMethod")
    if metodo not in ("claude.ai", "oauth_token"):
        return False, f"authMethod={metodo} (se esperaba claude.ai/oauth_token)"
    return True, st


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Server con las herramientas de la app
# ═══════════════════════════════════════════════════════════════════════════════

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mdn-tools")

# Estado por request (se resetea en cada /chat). Protegido por lock para
# que no se mezclen dos requests concurrentes (improbable, pero defensivo).
_state_lock = Lock()
_state = {
    "sel": {},
    "gasto": "0",
    "extrasLibres": [],
    "diaTipico": {},
    "diaTipicoCustom": None,
    "seccionesPorComida": {},
    "memoria": [],
    "resumen": {},
    "catalogo": "",
    # Lookup parseado del catálogo: {section_key: {meal, label, options: {id: label}}}
    "_cat_lookup": {},
    # Flags que setean las herramientas para que el bridge los devuelva al front
    "_guardar": False,
}


def _parse_catalogo(texto):
    """Parsea el formato 'key [Comida/Seccion]:id=Label|id2=Label2\\n...'"""
    lookup = {}
    for line in texto.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        head, rest = line.split(":", 1)
        # head = 'des_carb [Desayuno/Carbohidrato]'
        parts = head.split("[", 1)
        key = parts[0].strip()
        meal_sec = parts[1].rstrip("]").strip() if len(parts) > 1 else ""
        meal, sec_label = (meal_sec.split("/", 1) + [""])[:2]
        options = {}
        nada_id = None
        for opt in rest.split("|"):
            opt = opt.strip()
            if "=" not in opt:
                continue
            oid, olabel = opt.split("=", 1)
            oid = oid.strip()
            olabel = olabel.strip()
            options[oid] = olabel
            lower = olabel.lower()
            if lower in ("nada", "sin carbohidrato", "sin proteína", "sin hortalizas",
                         "sin aceite", "sin colores extra", "sin energetico", "ninguna extra", "0g"):
                nada_id = oid
        lookup[key] = {"meal": meal.strip(), "label": sec_label.strip(),
                       "options": options, "nada": nada_id}
    return lookup


def _defaults_sel(cat_lookup):
    """Devuelve todas las secciones en 'nada'."""
    sel = {}
    for key, info in cat_lookup.items():
        if info["nada"]:
            sel[key] = info["nada"]
    return sel


@mcp.tool()
def agregar_comida_libre(descripcion: str, kcal: float, proteina: float = 0,
                         carbohidratos: float = 0, grasa: float = 0) -> dict:
    """Agrega una comida que NO está en el catálogo (pizza, alfajor, asado, etc.)."""
    entry = {
        "id": f"libre_{int(datetime.now().timestamp()*1000)}",
        "desc": descripcion,
        "kcal": round(kcal),
        "p": round(proteina, 1),
        "c": round(carbohidratos, 1),
        "f": round(grasa, 1),
    }
    _state["extrasLibres"].append(entry)
    return {"ok": True, "agregado": descripcion, "kcal": round(kcal)}


@mcp.tool()
def ver_dia() -> dict:
    """Devuelve el resumen del día actual: macros totales, gasto, déficit."""
    return _state.get("resumen", {"mensaje": "sin datos de resumen"})


@mcp.tool()
def cargar_dia_tipico() -> dict:
    """Carga el día típico COMPLETO (las 5 comidas de golpe)."""
    base = _state.get("diaTipicoCustom") or _state.get("diaTipico", {})
    _state["sel"].update(base)
    return {"ok": True, "mensaje": "Día típico cargado"}


@mcp.tool()
def cargar_comida_tipica(comida: str) -> dict:
    """Carga SOLO UNA comida del día típico. Válidas: desayuno, media_manana, almuerzo, merienda, cena."""
    spc = _state.get("seccionesPorComida", {})
    prefijos = spc.get(comida)
    if not prefijos:
        return {"error": f"comida inválida: {comida}. Válidas: {', '.join(spc.keys())}"}
    base = _state.get("diaTipicoCustom") or _state.get("diaTipico", {})
    parcial = {k: v for k, v in base.items() if any(k.startswith(p) or k == p.rstrip("_") for p in prefijos)}
    if not parcial:
        return {"error": f"no encontré nada del día típico para {comida}"}
    _state["sel"].update(parcial)
    return {"ok": True, "comida": comida.replace("_", " "), "puestos": len(parcial)}


@mcp.tool()
def poner_gasto(kcal: float) -> dict:
    """Setea el gasto calórico del día (de WHOOP) en kcal."""
    _state["gasto"] = str(round(kcal))
    return {"ok": True, "gasto": round(kcal)}


@mcp.tool()
def seleccionar_opcion(seccion_key: str, opcion_id: str) -> dict:
    """Selecciona una opción del catálogo en una sección (como tocar un chip)."""
    cat = _state.get("_cat_lookup", {})
    sec = cat.get(seccion_key)
    if not sec:
        return {"error": f"sección inválida: {seccion_key}"}
    if opcion_id not in sec["options"]:
        return {"error": f"opción inválida: {opcion_id} en {seccion_key}"}
    _state["sel"][seccion_key] = opcion_id
    return {
        "ok": True,
        "seccion": seccion_key,
        "opcion": opcion_id,
        "puesto_label": sec["options"][opcion_id],
        "seccion_label": f"{sec['meal']} · {sec['label']}" if sec["meal"] else seccion_key,
    }


@mcp.tool()
def limpiar_dia() -> dict:
    """Pone TODAS las secciones en nada/0 y borra las comidas libres."""
    cat = _state.get("_cat_lookup", {})
    _state["sel"] = _defaults_sel(cat)
    _state["extrasLibres"] = []
    _state["gasto"] = "0"
    return {"ok": True, "mensaje": "Día puesto en cero. Si el usuario pidió cargar algo, HACELO AHORA."}


@mcp.tool()
def quitar_comida_libre(descripcion: str) -> dict:
    """Quita una comida libre buscándola por su descripción (o parte)."""
    t = descripcion.lower()
    for i, e in enumerate(_state["extrasLibres"]):
        if t in e.get("desc", "").lower():
            quitado = _state["extrasLibres"].pop(i)
            return {"ok": True, "quitado": quitado["desc"]}
    return {"error": f"no encontré una comida libre que coincida con: {descripcion}"}


@mcp.tool()
def guardar_dia() -> dict:
    """Guarda/archiva el día actual en el historial."""
    _state["_guardar"] = True
    return {"ok": True, "mensaje": "Marcado para guardar (el front lo archiva)"}


@mcp.tool()
def recordar(dato: str) -> dict:
    """Guarda un dato para recordar en futuras charlas."""
    if not dato.strip():
        return {"error": "dato vacío"}
    entry = {"id": f"m{int(datetime.now().timestamp()*1000)}", "texto": dato.strip(),
             "ts": int(datetime.now().timestamp() * 1000)}
    # Quitar duplicados
    _state["memoria"] = [entry] + [m for m in _state["memoria"]
                                    if m.get("texto", "").lower() != dato.strip().lower()]
    _state["memoria"] = _state["memoria"][:60]
    return {"ok": True, "recordado": dato.strip()}


@mcp.tool()
def olvidar(texto: str) -> dict:
    """Borra un dato de la memoria buscándolo por su texto."""
    t = texto.lower()
    for i, m in enumerate(_state["memoria"]):
        if t in m.get("texto", "").lower():
            olvidado = _state["memoria"].pop(i)
            return {"ok": True, "olvidado": olvidado["texto"]}
    return {"error": "no encontré eso en la memoria"}


# ═══════════════════════════════════════════════════════════════════════════════
# Atajos locales — SOLO cuando el mensaje ES el comando entero, nada más
# ═══════════════════════════════════════════════════════════════════════════════
#
# ⚠️ LECCIÓN (2026-08-13) — la primera versión buscaba SUBSTRINGS y rompió la app.
# "poné pechuga 200g en el almuerzo" contiene "pon"+"almuerzo" → cargaba el almuerzo
# típico ENTERO y pisaba el pedido. "poneme 2400 de gasto y cargame el desayuno"
# hacía solo el gasto. 6 de 22 mensajes reales salían mal.
#
# REGLA: el patrón se ancla con ^...$ y cubre el mensaje COMPLETO. Si sobra una sola
# palabra, va a Claude. Un atajo de más cuesta un día mal cargado; un atajo de menos
# cuesta 4 segundos. La asimetría manda.
#
# Tampoco hay atajo para "cómo voy" ni "guardá": piden matiz (análisis, confirmar
# qué se archiva) y una plantilla fija ahí se lee como que el asistente se volvió tonto.

import re

# Ruido que puede envolver un comando sin cambiar su significado
_CORTESIA = r'(?:por\s+favor|porfa|dale|che|ok|listo|gracias|ahora|ya)'
_LIMPIA_BORDES = re.compile(
    rf'^(?:{_CORTESIA}[\s,]+)+|(?:[\s,]+{_CORTESIA})+$|[\s.,!¡?¿]+$', re.I)

def _normalizar(msg):
    """Baja a minúsculas, saca acentos de las vocales y poda cortesía/puntuación."""
    m = msg.strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        m = m.replace(a, b)
    prev = None
    while prev != m:                       # podar en capas: "dale, limpia el dia porfa."
        prev = m
        m = _LIMPIA_BORDES.sub("", m).strip()
    return m

# Verbo opcional al principio: "poneme", "carga", "cargame", "meteme"...
_V_PONER = r'(?:pon[eé]?(?:me|le)?|carga(?:me|le)?|met[eé]?(?:me|le)?|anota(?:me)?|marca(?:me)?)'

# ── Gasto: el mensaje entero es el gasto y NADA más ────────────────────────────
# ✅ "2400 de gasto" · "poneme 2400 de gasto" · "gasto 2400" · "gasto: 2400 kcal"
# ❌ "poneme 2400 de gasto y cargame el desayuno"  (sobra texto → Claude)
# ❌ "gaste 2400 hoy, cuanto deficit tengo?"       (es una pregunta → Claude)
_RE_GASTO = [
    re.compile(rf'^{_V_PONER}?\s*(\d{{3,5}})\s*(?:kcal|cal|calorias)?\s*(?:de\s+)?gasto$'),
    re.compile(rf'^{_V_PONER}?\s*(?:el\s+|mi\s+)?gasto\s*(?:en|a|:|=)?\s*(\d{{3,5}})\s*(?:kcal|cal|calorias)?$'),
]

# ── Día típico COMPLETO ────────────────────────────────────────────────────────
# ✅ "carga mi dia tipico" · "el dia tipico" · "lo de siempre"
# ❌ "cargame el dia tipico pero sin la cena"  (tiene excepción → Claude)
_RE_DIA_TIPICO = re.compile(
    rf'^{_V_PONER}?\s*(?:el\s+|mi\s+)?(?:dia\s+tipico|lo\s+de\s+siempre|todo\s+el\s+dia)$')

# ── UNA comida típica ──────────────────────────────────────────────────────────
# ✅ "cargame el desayuno tipico" · "el almuerzo de siempre"
# ❌ "poneme el desayuno con avena en vez de harina"  (pide un cambio → Claude)
_COMIDAS = {'desayuno': 'desayuno', 'media manana': 'media_manana',
            'almuerzo': 'almuerzo', 'merienda': 'merienda', 'cena': 'cena'}
_RE_COMIDA_TIPICA = re.compile(
    rf'^{_V_PONER}?\s*(?:el\s+|la\s+|mi\s+)?({"|".join(_COMIDAS)})'
    r'\s*(?:tipico|tipica|de\s+siempre|habitual|de\s+todos\s+los\s+dias)$')

# ── Limpiar ────────────────────────────────────────────────────────────────────
# ✅ "limpia el dia" · "borra todo" · "empeza de cero"
# ❌ "limpia el dia y cargame el desayuno"  (compuesto → Claude)
_RE_LIMPIAR = re.compile(
    r'^(?:limpia(?:me|r)?|borra(?:me|r)?|resetea(?:me|r)?|vacia(?:me|r)?|empeza(?:r)?)'
    r'\s*(?:el\s+|todo\s+el\s+|de\s+)?(?:dia|todo|cero)$')


# ⚠️ LECCIÓN (2026-08-13, segunda vuelta) — un atajo que Claude no ve, le corta el hilo.
# Guión real: "cargame el almuerzo tipico" (atajo, no pasa por Claude) → "no, pechuga de
# 200 mejor" → Claude, que nunca se enteró del almuerzo, puso la pechuga en el DESAYUNO.
# El atajo no estaba mal escrito: faltaba contarle lo que había hecho. Por eso todo atajo
# deja acá su rastro, y el próximo pedido que sí llega a Claude lo lleva como contexto.
_acciones_atajo = []          # se vacía cuando se lo lleva un pedido a Claude


def _atajo_local(msg):
    """Resuelve el mensaje sin Claude SOLO si es un comando exacto.

    Retorna (reply, True) si lo resolvió, o (None, False) para que vaya a Claude.
    Ante la mínima duda devuelve False: es más barato esperar 4s que arruinar el día.
    """
    m = _normalizar(msg)
    if not m:
        return None, False

    # Gasto
    for rx in _RE_GASTO:
        mo = rx.match(m)
        if mo:
            kcal = int(mo.group(1))
            if 100 <= kcal <= 9999:          # fuera de rango = probablemente no es gasto
                poner_gasto(kcal)
                _acciones_atajo.append(f'Usuario: "{msg}" → puse el gasto en {kcal} kcal.')
                return f"Gasto: **{kcal} kcal**.", True
            return None, False

    # Día típico entero
    if _RE_DIA_TIPICO.match(m):
        base = _state.get("diaTipicoCustom") or _state.get("diaTipico", {})
        if not base:
            return None, False               # sin día típico cargado, que lo explique Claude
        cargar_dia_tipico()
        _acciones_atajo.append(f'Usuario: "{msg}" → cargué el día típico completo.')
        return "Listo, día típico cargado.", True

    # Una comida típica
    mo = _RE_COMIDA_TIPICA.match(m)
    if mo:
        nombre = mo.group(1)
        r = cargar_comida_tipica(_COMIDAS[nombre])
        if "error" in r:
            return None, False               # que Claude explique por qué no pudo
        _acciones_atajo.append(
            f'Usuario: "{msg}" → cargué el {nombre} típico '
            f'(secciones {nombre}, ninguna otra comida).')
        return f"Listo, {nombre} típico cargado.", True

    # Limpiar
    if _RE_LIMPIAR.match(m):
        limpiar_dia()
        _acciones_atajo.append(f'Usuario: "{msg}" → puse todo el día en cero.')
        return "Día en cero.", True

    return None, False


# ═══════════════════════════════════════════════════════════════════════════════
# Motor: UN proceso `claude` vivo, reusado entre pedidos
# ═══════════════════════════════════════════════════════════════════════════════
#
# Medido el 2026-08-13 (spike_persistente.py) sobre un pedido típico:
#     arrancar el proceso `claude.exe` .... 6,81 s   ← el 65% del tiempo
#     inferencia ........................... 4,07 s   ← lo único irreducible
#
# `query()` levanta un proceso nuevo por pedido, así que pagaba los 6,81 s SIEMPRE.
# `ClaudeSDKClient` lo deja vivo: se paga una vez y los pedidos siguientes salen en
# ~4 s. Es la mejora real de velocidad — y, a diferencia de recortar herramientas o
# meter atajos con regex, no cuesta ni una gota de inteligencia.
#
# Además el proceso conserva la conversación entre pedidos (verificado: un
# `session_id` nuevo NO la aísla), así que "no, eso no" o "agregale queso" entienden
# a qué se refieren sin reenviar el historial en cada vuelta.

import hashlib
import threading
import queue as _queue


def _instantanea_estado():
    """Lo que el front necesita para pintar el día. Llamar con _state_lock tomado."""
    return {
        "sel": dict(_state["sel"]),
        "gasto": _state["gasto"],
        "extrasLibres": list(_state["extrasLibres"]),
        "memoria": list(_state["memoria"]),
        "guardar": _state["_guardar"],
    }

# El loop de asyncio vive en un hilo propio y NO muere entre pedidos: es lo que
# mantiene vivo al subproceso del SDK. Flask (sync, multihilo) le manda trabajo.
class _MotorClaude:
    """Dueño del proceso `claude`. Serializa los pedidos y se recupera solo si muere."""

    # Reciclar cada tantos pedidos: la conversación acumulada crece y encarece cada
    # vuelta. 40 da charla larga sin que el contexto se vaya de las manos.
    MAX_PEDIDOS = 40

    def __init__(self):
        self._loop = None
        self._hilo = None
        self._listo = threading.Event()
        self._lock = threading.Lock()      # un pedido por vez (el CLI es una sola conversación)
        self._client = None
        self._firma = None                 # (modelo, hash del prompt base)
        self._conv_id = None               # id de conversación del front
        self._pedidos = 0
        self._arrancar_loop()

    # ── infraestructura ────────────────────────────────────────────────────────
    def _arrancar_loop(self):
        def correr():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._listo.set()
            self._loop.run_forever()
        self._hilo = threading.Thread(target=correr, daemon=True, name="motor-claude")
        self._hilo.start()
        self._listo.wait(timeout=10)

    def _correr(self, coro, timeout):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    # ── ciclo de vida del cliente ──────────────────────────────────────────────
    async def _abrir(self, modelo, prompt_base):
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        opts = ClaudeAgentOptions(
            model=modelo,
            system_prompt=prompt_base,
            mcp_servers={"mdn": {"type": "sdk", "name": "mdn-tools",
                                 "instance": mcp._mcp_server}},
            # El prompt le pide abrir links y buscar datos oficiales de marcas: sin
            # estas dos, esa instrucción era letra muerta y estimaba a ojo.
            tools=["WebSearch", "WebFetch"],
            setting_sources=[],            # no cargar CLAUDE.md ni settings del usuario
            permission_mode="bypassPermissions",
            max_turns=8,
            effort="low",
            # Sin esto el SDK entrega bloques ya terminados y el texto aparece de golpe
            # al final; con esto llegan los deltas y la respuesta se ve escribirse.
            include_partial_messages=True,
        )
        c = ClaudeSDKClient(options=opts)
        await c.connect()
        return c

    async def _cerrar(self, client):
        try:
            await client.disconnect()
        except Exception:
            pass

    async def _asegurar(self, modelo, prompt_base, conv_id):
        """Devuelve un cliente conectado, reciclándolo si cambió algo o se gastó."""
        firma = (modelo, hashlib.sha1(prompt_base.encode("utf-8")).hexdigest())
        motivo = None
        if self._client is None:
            motivo = "primer pedido"
        elif firma != self._firma:
            motivo = "cambió el modelo o el catálogo"
        elif conv_id and conv_id != self._conv_id:
            motivo = "conversación nueva"
        elif self._pedidos >= self.MAX_PEDIDOS:
            motivo = f"{self._pedidos} pedidos acumulados"

        if motivo:
            if self._client is not None:
                log.info(f"[motor] reciclando el proceso: {motivo}")
                await self._cerrar(self._client)
                self._client = None
            t0 = datetime.now()
            self._client = await self._abrir(modelo, prompt_base)
            self._firma, self._conv_id, self._pedidos = firma, conv_id, 0
            log.info(f"[motor] proceso nuevo listo en {(datetime.now()-t0).total_seconds():.1f}s"
                     f" (modelo={modelo})")
        return self._client

    # ── un pedido ──────────────────────────────────────────────────────────────
    async def _pedir(self, client, prompt, imagenes=None, emitir=None):
        """Corre un pedido. Si `emitir` viene, avisa cada bloque apenas llega.

        Los 4 s de inferencia no se pueden bajar, pero mirar una pantalla quieta
        durante 4 s y ver la respuesta escribirse no se sienten igual. Y como las
        herramientas corren ANTES de que el modelo redacte la confirmación, el día
        se actualiza en la pantalla bastante antes de que termine de hablar.
        """
        from claude_agent_sdk.types import (SystemMessage, AssistantMessage,
                                            TextBlock, ResultMessage, StreamEvent)
        if imagenes:
            # Con imágenes hay que mandar el mensaje entero como bloques (igual que la
            # API). El prompt de la app promete leer etiquetas nutricionales y fotos de
            # platos: antes se descartaban en silencio y el modelo estimaba a ciegas.
            bloques = [{"type": "image",
                        "source": {"type": "base64",
                                   "media_type": im.get("media", "image/jpeg"),
                                   "data": im.get("b64", "")}}
                       for im in imagenes if im.get("b64")]
            bloques.append({"type": "text", "text": prompt})

            async def stream():
                yield {"type": "user",
                       "message": {"role": "user", "content": bloques},
                       "parent_tool_use_id": None,
                       "session_id": "default"}
            await client.query(stream())
        else:
            await client.query(prompt)
        texto, herramientas = [], []
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage):
                d = msg.data or {}
                if d.get("subtype") == "init":
                    fuente = d.get("apiKeySource")
                    # PASO 3 del patrón MAX BRIDGE: assert anti-facturación
                    if fuente in FACTURABLES:
                        raise RuntimeError(
                            f"ABORTADO: apiKeySource={fuente} → facturaría por API."
                            " Correr `claude auth login` y verificar la suscripción Max.")
            elif isinstance(msg, StreamEvent):
                # Deltas: solo para pintar en vivo. El texto que se devuelve sale de los
                # AssistantMessage de abajo, que son la versión final y completa.
                if emitir:
                    ev = msg.event or {}
                    if ev.get("type") == "content_block_delta":
                        d = ev.get("delta") or {}
                        if d.get("type") == "text_delta" and d.get("text"):
                            emitir({"tipo": "delta", "texto": d["text"]})
            elif isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        texto.append(b.text)
                        if emitir:
                            # Cierra el bloque: el front reemplaza lo que venía pintando
                            # con la versión final (evita duplicar los deltas).
                            emitir({"tipo": "texto", "texto": b.text})
                    elif type(b).__name__ == "ToolUseBlock":
                        nombre = getattr(b, "name", "?").replace("mcp__mdn__", "")
                        herramientas.append(nombre)
                        if emitir:
                            # La herramienta ya modificó _state: mandar el día al toque,
                            # sin esperar a que el modelo termine de escribir.
                            with _state_lock:
                                emitir({"tipo": "tool", "nombre": nombre,
                                        "state": _instantanea_estado()})
            elif isinstance(msg, ResultMessage):
                break
        return "\n".join(texto).strip(), herramientas

    def preguntar(self, prompt, modelo, prompt_base, conv_id=None, imagenes=None,
                  timeout=180):
        """API sincrónica para Flask. Serializa y reintenta una vez si el proceso murió."""
        with self._lock:
            for intento in (1, 2):
                try:
                    client = self._correr(self._asegurar(modelo, prompt_base, conv_id),
                                          timeout=90)
                    texto, tools = self._correr(self._pedir(client, prompt, imagenes),
                                                timeout=timeout)
                    self._pedidos += 1
                    return texto or "(listo)", tools
                except RuntimeError:
                    raise                       # anti-facturación: no reintentar
                except Exception as e:
                    if intento == 2:
                        raise
                    # El proceso pudo morir (sesión vieja, CLI actualizado, etc.):
                    # tirarlo y rearmar. Un reintento, no un bucle.
                    log.warning(f"[motor] pedido falló ({type(e).__name__}: {e}); "
                                f"rearmo el proceso y reintento")
                    if self._client is not None:
                        try:
                            self._correr(self._cerrar(self._client), timeout=15)
                        except Exception:
                            pass
                    self._client = None

    def preguntar_stream(self, prompt, modelo, prompt_base, conv_id=None, imagenes=None,
                         timeout=180):
        """Igual que preguntar(), pero devuelve un generador de eventos.

        El coro corre en el hilo del motor y va dejando eventos en una cola; este
        generador (hilo de Flask) los va sacando. Sin reintento: una vez que empezó a
        salir texto no se puede rebobinar, así que si falla el front cae a /chat.
        """
        cola = _queue.Queue()
        FIN = object()

        with self._lock:
            client = self._correr(self._asegurar(modelo, prompt_base, conv_id), timeout=90)

            async def correr():
                try:
                    texto, tools = await self._pedir(client, prompt, imagenes,
                                                     emitir=cola.put)
                    cola.put({"tipo": "fin", "reply": texto or "(listo)", "tools": tools})
                except Exception as e:
                    cola.put({"tipo": "error", "error": str(e)})
                finally:
                    cola.put(FIN)

            fut = asyncio.run_coroutine_threadsafe(correr(), self._loop)
            try:
                while True:
                    try:
                        ev = cola.get(timeout=timeout)
                    except _queue.Empty:
                        fut.cancel()
                        yield {"tipo": "error", "error": "el modelo no respondió a tiempo"}
                        return
                    if ev is FIN:
                        break
                    yield ev
                self._pedidos += 1
            finally:
                if not fut.done():
                    fut.cancel()

    def estado(self):
        return {"vivo": self._client is not None, "pedidos": self._pedidos,
                "modelo": self._firma[0] if self._firma else None}


_motor = _MotorClaude()


def _partir_prompt(system_prompt):
    """Separa la parte ESTABLE del prompt (reglas + catálogo) de la volátil.

    El estado del día y la memoria cambian en cada pedido; si fueran al system prompt
    obligarían a rearmar el proceso cada vez y no habría persistencia posible. Van
    dentro del mensaje. El corte es donde el front pega el estado.
    """
    for marca in ("\n\nEstado actual del dia:", "\n\nEstado actual del día:"):
        i = system_prompt.find(marca)
        if i != -1:
            return system_prompt[:i], system_prompt[i:].strip()
    return system_prompt, ""


def _prompt_del_pedido(mensaje, volatil, historial, sembrar):
    """Arma el mensaje: estado fresco + lo que hicieron los atajos + historial + pedido."""
    partes = []
    if volatil:
        partes.append(volatil)

    # Lo que resolvieron los atajos desde el último pedido a Claude. Sin esto, el
    # modelo no se entera de esas vueltas y responde fuera de contexto (ver lección
    # arriba de _atajo_local).
    if _acciones_atajo:
        partes.append("=== HECHO DESDE TU ÚLTIMA RESPUESTA (resuelto por la app, sin vos) ===\n"
                      + "\n".join(_acciones_atajo)
                      + "\n=== FIN ===")
        _acciones_atajo.clear()

    # El proceso conserva la charla entre pedidos, así que el historial solo hace
    # falta cuando se acaba de crear (arranque, reciclado, o recarga de la página).
    if sembrar and historial:
        lineas = []
        for m in historial[-12:]:
            rol = "Usuario" if m.get("role") == "user" else "Asistente"
            txt = (m.get("text") or "").strip()
            if txt:
                lineas.append(f"{rol}: {txt}")
        if lineas:
            partes.append("=== CONVERSACIÓN PREVIA ===\n" + "\n".join(lineas) + "\n=== FIN ===")

    partes.append(mensaje)
    return "\n\n".join(partes)


# ═══════════════════════════════════════════════════════════════════════════════
# Flask app
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__, static_folder=str(AQUI), static_url_path="/static")
CORS(app)  # el front viene de github.io o localhost — necesita CORS

# ── Servir la PWA directamente (resuelve mixed content desde el celular) ──
# El celular abre http://<tailscale-ip>:8793/ y todo es mismo origen.
PWA_FILES = {"index.html", "sw.js", "manifest.json", "hot-pot-192.png", "hot-pot-512.png"}

@app.route("/", methods=["GET"])
def pwa_root():
    """Sirve la PWA desde el bridge — mismo origen, sin CORS ni mixed content."""
    resp = send_from_directory(str(AQUI), "index.html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

@app.route("/<path:filename>", methods=["GET"])
def pwa_file(filename):
    """Sirve archivos estáticos de la PWA (sw.js, manifest, iconos)."""
    if filename in PWA_FILES or filename.endswith(".png"):
        return send_from_directory(str(AQUI), filename)
    return jsonify({"error": "not found"}), 404


@app.route("/status", methods=["GET"])
def status():
    """Health check rápido para que el front sepa si el bridge está vivo."""
    return jsonify({"ok": True, "version": "2.0.0", "port": PORT,
                    "motor": _motor.estado()})


@app.route("/warmup", methods=["POST"])
def warmup():
    """Arranca el proceso `claude` de fondo, apenas la app abre.

    Arrancarlo cuesta ~6,8 s. Si esperáramos al primer mensaje, ese mensaje tardaría
    ~11 s y el resto ~4 s — justo la primera impresión es la peor. Pidiéndolo acá, el
    proceso ya está listo cuando el usuario termina de escribir.
    """
    try:
        data = flask_request.get_json(force=True) or {}
    except Exception:
        data = {}
    modelo = data.get("model", "claude-haiku-4-5-20251001")
    prompt_base, _ = _partir_prompt(data.get("systemPrompt", ""))
    if not prompt_base.strip():
        return jsonify({"ok": False, "motivo": "sin systemPrompt"}), 400

    def calentar():
        try:
            t0 = datetime.now()
            with _motor._lock:
                _motor._correr(_motor._asegurar(modelo, prompt_base, data.get("convId")),
                               timeout=90)
            log.info(f"[warmup] proceso listo en {(datetime.now()-t0).total_seconds():.1f}s")
        except Exception as e:
            log.warning(f"[warmup] falló: {e}")

    threading.Thread(target=calentar, daemon=True, name="warmup").start()
    return jsonify({"ok": True, "calentando": True})


class _PedidoInvalido(Exception):
    pass


def _preparar(data):
    """Valida el pedido y deja _state listo. Compartido por /chat y /chat/stream:
    si cada uno armara el estado por su cuenta, tarde o temprano divergen."""
    mensaje = (data.get("message") or "").strip()
    imagenes = data.get("images", []) or []
    if not mensaje and not imagenes:
        raise _PedidoInvalido("message vacío")
    if imagenes and not mensaje:
        mensaje = "¿Qué ves en esta imagen? Cargá lo que corresponda."

    estado = data.get("state", {}) or {}
    with _state_lock:
        _state["sel"] = dict(estado.get("sel", {}))
        _state["gasto"] = str(estado.get("gasto", "0"))
        _state["extrasLibres"] = list(estado.get("extrasLibres", []))
        _state["diaTipico"] = dict(estado.get("diaTipico", {}))
        _state["diaTipicoCustom"] = estado.get("diaTipicoCustom")
        _state["seccionesPorComida"] = dict(estado.get("seccionesPorComida", {}))
        _state["memoria"] = list(estado.get("memoria", []))
        _state["resumen"] = dict(estado.get("resumen", {}))
        _state["catalogo"] = estado.get("catalogo", "")
        _state["_cat_lookup"] = _parse_catalogo(_state["catalogo"])
        _state["_guardar"] = False

    prompt_base, volatil = _partir_prompt(data.get("systemPrompt", ""))
    conv_id = data.get("convId") or None
    # Si el proceso se va a rearmar, hay que reponerle la charla previa.
    sembrar = _motor.estado()["pedidos"] == 0 or conv_id != _motor._conv_id
    return {
        "mensaje": mensaje,
        "imagenes": imagenes,
        "modelo": data.get("model", "claude-haiku-4-5-20251001"),
        "conv_id": conv_id,
        "prompt_base": prompt_base,
        "prompt": _prompt_del_pedido(mensaje, volatil,
                                     data.get("history", []) or [], sembrar),
    }


@app.route("/chat", methods=["POST"])
def chat():
    """Pedido de una sola vuelta: responde cuando terminó todo.

    Lo usa el front como respaldo si el streaming no está disponible.
    """
    try:
        data = flask_request.get_json(force=True)
    except Exception:
        return jsonify({"error": "JSON inválido"}), 400
    try:
        p = _preparar(data)
    except _PedidoInvalido as e:
        return jsonify({"error": str(e)}), 400

    t0 = datetime.now()
    herramientas = []

    # ── Atajo: solo si el mensaje ES el comando entero (ver _atajo_local) ──
    # Con imagen nunca hay atajo: hay que mirarla.
    reply, fue_atajo = (None, False) if p["imagenes"] else _atajo_local(p["mensaje"])
    if fue_atajo:
        log.info(f"[ATAJO] {(datetime.now()-t0).total_seconds():.3f}s | {p['mensaje'][:60]}")
    else:
        try:
            reply, herramientas = _motor.preguntar(
                p["prompt"], p["modelo"], p["prompt_base"], p["conv_id"],
                imagenes=p["imagenes"])
        except Exception as e:
            log.error(f"Error hablando con Claude: {e}\n{traceback.format_exc()}")
            return jsonify({"error": str(e)}), 500
        n_img = len(p["imagenes"])
        log.info(f"[chat] {(datetime.now()-t0).total_seconds():.1f}s | modelo={p['modelo']}"
                 + (f" | {n_img} img" if n_img else "")
                 + f" | tools={herramientas or '-'} | {p['mensaje'][:60]}")

    with _state_lock:
        nuevo_estado = _instantanea_estado()

    return jsonify({
        "reply": reply,
        "state": nuevo_estado,
        "duracion": round((datetime.now() - t0).total_seconds(), 1),
        "atajo": fue_atajo,
        "tools": herramientas,
    })


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    """Igual que /chat pero por SSE: manda el texto mientras se escribe y el día
    apenas cada herramienta lo toca, en vez de todo junto al final.

    No baja los ~4 s de inferencia — baja lo que se siente, que es lo que quedaba
    por mejorar sin recortarle nada al asistente.
    """
    try:
        data = flask_request.get_json(force=True)
    except Exception:
        return jsonify({"error": "JSON inválido"}), 400
    try:
        p = _preparar(data)
    except _PedidoInvalido as e:
        return jsonify({"error": str(e)}), 400

    t0 = datetime.now()

    def evento(d):
        return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"

    def generar():
        # Atajo: sale entero, pero por el mismo canal para que el front tenga un solo camino
        reply, fue_atajo = (None, False) if p["imagenes"] else _atajo_local(p["mensaje"])
        if fue_atajo:
            log.info(f"[ATAJO] {(datetime.now()-t0).total_seconds():.3f}s | {p['mensaje'][:60]}")
            with _state_lock:
                st = _instantanea_estado()
            yield evento({"tipo": "fin", "reply": reply, "state": st,
                          "atajo": True, "tools": [],
                          "duracion": round((datetime.now()-t0).total_seconds(), 2)})
            return

        tools = []
        try:
            for ev in _motor.preguntar_stream(p["prompt"], p["modelo"], p["prompt_base"],
                                              p["conv_id"], imagenes=p["imagenes"]):
                if ev["tipo"] == "tool":
                    tools.append(ev["nombre"])
                    yield evento(ev)
                elif ev["tipo"] in ("texto", "delta"):
                    yield evento(ev)
                elif ev["tipo"] == "error":
                    log.error(f"[stream] {ev['error']}")
                    yield evento(ev)
                    return
                elif ev["tipo"] == "fin":
                    with _state_lock:
                        st = _instantanea_estado()
                    dur = (datetime.now() - t0).total_seconds()
                    n_img = len(p["imagenes"])
                    log.info(f"[stream] {dur:.1f}s | modelo={p['modelo']}"
                             + (f" | {n_img} img" if n_img else "")
                             + f" | tools={tools or '-'} | {p['mensaje'][:60]}")
                    yield evento({"tipo": "fin", "reply": ev["reply"], "state": st,
                                  "atajo": False, "tools": tools,
                                  "duracion": round(dur, 1)})
        except Exception as e:
            log.error(f"Error en el stream: {e}\n{traceback.format_exc()}")
            yield evento({"tipo": "error", "error": str(e)})

    return app.response_class(generar(), mimetype="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def _puerto_ocupado(puerto):
    """¿Ya hay algo escuchando ahí? Evita dos bridges peleándose el puerto —
    que fue justo lo que pasó el 2026-08-13 con SPEED en el 8792: el segundo
    arrancaba 'bien' pero los pedidos le llegaban al primero."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def main():
    parser = argparse.ArgumentParser(description="MDN Bridge — Max subscription proxy")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("MDN BRIDGE — Mi Día Nutricional + Claude Max")
    log.info("=" * 60)

    if _puerto_ocupado(args.port):
        try:
            import urllib.request
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{args.port}/status", timeout=3) as r:
                if json.loads(r.read().decode()).get("ok"):
                    log.error(f"Ya hay un MDN Bridge escuchando en el {args.port}. "
                              f"No arranco un segundo.")
                    return 0
        except Exception:
            pass
        log.error(f"El puerto {args.port} está ocupado por OTRA cosa. "
                  f"Arrancar con --port <otro> o liberarlo.")
        return 1

    # Preflight
    ok, st = preflight()
    if not ok:
        log.error(f"Preflight FAIL: {st}")
        log.error("Correr: claude auth login")
        return 1
    log.info(f"Preflight OK: {st.get('authMethod')} | {st.get('subscriptionType')} | {st.get('email')}")

    # Verificar que el MCP server tenga las herramientas
    log.info(f"MCP tools: {len(mcp._tool_manager._tools)} herramientas registradas")

    puerto = args.port
    log.info(f"Escuchando en 0.0.0.0:{puerto}")
    log.info(f"Desde la PC:  http://localhost:{puerto}/status")
    log.info(f"Desde Tailscale: http://100.110.55.41:{puerto}/status")

    app.run(host="0.0.0.0", port=puerto, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.error("Error fatal:\n" + traceback.format_exc())
        sys.exit(1)
