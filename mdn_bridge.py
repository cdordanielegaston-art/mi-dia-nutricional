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

from flask import Flask, request as flask_request, jsonify
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
# Llamada al Agent SDK
# ═══════════════════════════════════════════════════════════════════════════════

async def llamar_claude(prompt, system_prompt, modelo="claude-haiku-4-5-20251001"):
    """Ejecuta una conversación completa con Claude vía Agent SDK + MCP tools."""
    from claude_agent_sdk import query, ClaudeAgentOptions
    from claude_agent_sdk.types import SystemMessage, AssistantMessage, TextBlock, ResultMessage

    opts = ClaudeAgentOptions(
        model=modelo,
        system_prompt=system_prompt,
        mcp_servers={
            "mdn": {
                "type": "sdk",
                "name": "mdn-tools",
                "instance": mcp._mcp_server,
            }
        },
        tools=[],                    # sin herramientas built-in del CLI
        setting_sources=[],          # no cargar CLAUDE.md ni settings
        permission_mode="bypassPermissions",
        max_turns=8,
        effort="low",
    )

    texto_final = []
    api_key_source = None
    model_usado = None

    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, SystemMessage):
            data = msg.data or {}
            if data.get("subtype") == "init":
                api_key_source = data.get("apiKeySource")
                model_usado = data.get("model")
                log.info(f"[SDK init] apiKeySource={api_key_source} model={model_usado}")
                # PASO 3: assert anti-facturación
                if api_key_source in FACTURABLES:
                    raise RuntimeError(
                        f"ABORTADO: apiKeySource={api_key_source} → facturaría por API."
                        " Correr `claude auth login` y verificar la suscripción Max."
                    )
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    texto_final.append(b.text)

    return "\n".join(texto_final).strip() or "(listo)"


# ═══════════════════════════════════════════════════════════════════════════════
# Flask app
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)  # el front viene de github.io o localhost — necesita CORS


@app.route("/status", methods=["GET"])
def status():
    """Health check rápido para que el front sepa si el bridge está vivo."""
    return jsonify({"ok": True, "version": "1.0.0", "port": PORT})


@app.route("/chat", methods=["POST"])
def chat():
    """Endpoint principal: recibe un mensaje + estado, devuelve reply + estado nuevo."""
    try:
        data = flask_request.get_json(force=True)
    except Exception:
        return jsonify({"error": "JSON inválido"}), 400

    mensaje = data.get("message", "").strip()
    if not mensaje:
        return jsonify({"error": "message vacío"}), 400

    estado = data.get("state", {})
    modelo = data.get("model", "claude-haiku-4-5-20251001")
    system_prompt = data.get("systemPrompt", "")

    # ── Inicializar el estado para esta request ──
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

    t0 = datetime.now()
    try:
        reply = asyncio.run(llamar_claude(mensaje, system_prompt, modelo))
    except Exception as e:
        log.error(f"Error en llamar_claude: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

    duracion = (datetime.now() - t0).total_seconds()
    log.info(f"[chat] {duracion:.1f}s | modelo={modelo} | msg={mensaje[:60]}")

    # ── Devolver el estado modificado por las herramientas ──
    with _state_lock:
        nuevo_estado = {
            "sel": dict(_state["sel"]),
            "gasto": _state["gasto"],
            "extrasLibres": list(_state["extrasLibres"]),
            "memoria": list(_state["memoria"]),
            "guardar": _state["_guardar"],
        }

    return jsonify({
        "reply": reply,
        "state": nuevo_estado,
        "duracion": round(duracion, 1),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="MDN Bridge — Max subscription proxy")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("MDN BRIDGE — Mi Día Nutricional + Claude Max")
    log.info("=" * 60)

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
