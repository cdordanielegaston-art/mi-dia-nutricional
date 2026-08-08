# -*- coding: utf-8 -*-
"""Prueba REAL del adaptador de Gemini de Mi Dia Nutricional.

Manda a la API de Google exactamente el mismo formato de request que arma la app,
para descubrir errores de formato ACA y no cuando Gaston este cargando la cena.

Como se usa:
  1. Sacar la API key gratis en https://aistudio.google.com/apikey
  2. Pegarla SOLA en un archivo de texto llamado  clave_google.txt  (al lado de este script)
  3. Doble clic, o:  python probar_gemini.py

La clave NO se imprime nunca. El archivo clave_google.txt esta en .gitignore.
"""
import json, sys, io, ssl, pathlib, urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
AQUI = pathlib.Path(__file__).resolve().parent

# ── Norton intercepta el HTTPS de esta PC y su CA no esta en certifi; ademas Python
#    3.13+ activa VERIFY_X509_STRICT, que el certificado de Norton viola.
BUNDLE = pathlib.Path(r"C:\Users\Gasaton\.claude\ca-bundle-norton.pem")
def contexto_ssl():
    ctx = ssl.create_default_context(cafile=str(BUNDLE) if BUNDLE.exists() else None)
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx

MODELO = "gemini-3.6-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent"

# Las mismas 2 herramientas que mas se usan en la app (una con parametros, una sin)
DECLS = [
    {"name": "agregar_comida_libre",
     "description": "Agrega una comida que no esta en el catalogo, con sus macros.",
     "parameters": {"type": "object",
                    "properties": {"descripcion": {"type": "string"}, "kcal": {"type": "number"},
                                   "p": {"type": "number"}, "c": {"type": "number"}, "f": {"type": "number"}},
                    "required": ["descripcion", "kcal"]}},
    # OJO: sin parametros va SIN 'parameters' (un properties vacio da HTTP 400)
    {"name": "ver_dia", "description": "Devuelve el resumen del dia actual."},
]

def pedir(body, key):
    req = urllib.request.Request(URL, method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=60, context=contexto_ssl()) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

def partes(data):
    try: return data["candidates"][0]["content"]["parts"]
    except Exception: return []

def main():
    f = AQUI / "clave_google.txt"
    if not f.exists():
        print("Falta el archivo clave_google.txt")
        print(f"Crealo aca y pega adentro la API key (nada mas):\n  {f}")
        print("Se saca gratis en https://aistudio.google.com/apikey")
        return 1
    key = f.read_text(encoding="utf-8").strip()
    if not key:
        print("clave_google.txt esta vacio."); return 1
    print(f"Clave leida: {len(key)} caracteres, empieza con '{key[:4]}...'  (no la imprimo entera)\n")

    fallos = []

    # 1) Que conteste algo
    print("[1/4] Responde texto...", end=" ", flush=True)
    st, d = pedir({"systemInstruction": {"parts": [{"text": "Contesta en una linea, en espanol rioplatense."}]},
                   "contents": [{"role": "user", "parts": [{"text": "Cuantas calorias tiene 100 g de pechuga de pollo?"}]}],
                   "generationConfig": {"maxOutputTokens": 2048}}, key)
    if st == 200 and any("text" in p for p in partes(d)):
        txt = " ".join(p.get("text", "") for p in partes(d)).strip()
        print("OK ->", txt[:90])
    else:
        print("FALLA:", st, str(d)[:300]); fallos.append("texto")

    # 2) Function calling: el corazon de la app
    print("[2/4] Llama a las herramientas...", end=" ", flush=True)
    st, d = pedir({"systemInstruction": {"parts": [{"text": "Sos el asistente de una app de nutricion. Usa las herramientas."}]},
                   "contents": [{"role": "user", "parts": [{"text": "Comi un alfajor de chocolate"}]}],
                   "tools": [{"functionDeclarations": DECLS}],
                   "generationConfig": {"maxOutputTokens": 2048}}, key)
    llamada = next((p["functionCall"] for p in partes(d) if "functionCall" in p), None)
    if st == 200 and llamada:
        print(f"OK -> pidio {llamada['name']}({json.dumps(llamada.get('args', {}), ensure_ascii=False)[:80]})")
    else:
        print("FALLA:", st, str(d)[:300]); fallos.append("herramientas")

    # 3) Devolverle el resultado de la herramienta (el viaje de vuelta)
    print("[3/4] Cierra el circuito con el resultado...", end=" ", flush=True)
    if llamada:
        st, d = pedir({"contents": [
                          {"role": "user", "parts": [{"text": "Comi un alfajor de chocolate"}]},
                          {"role": "model", "parts": [{"functionCall": llamada}]},
                          {"role": "user", "parts": [{"functionResponse": {"name": llamada["name"],
                                                     "response": {"resultado": {"ok": True, "kcal_total_dia": 1890}}}}]}],
                       "tools": [{"functionDeclarations": DECLS}],
                       "generationConfig": {"maxOutputTokens": 2048}}, key)
        if st == 200 and any("text" in p for p in partes(d)):
            print("OK ->", " ".join(p.get("text", "") for p in partes(d)).strip()[:90])
        else:
            print("FALLA:", st, str(d)[:300]); fallos.append("resultado de herramienta")
    else:
        print("SALTEADO (fallo el paso 2)"); fallos.append("resultado de herramienta")

    # 4) Busqueda de Google + herramientas propias en el MISMO pedido
    print("[4/4] Busqueda web junto con las herramientas...", end=" ", flush=True)
    st, d = pedir({"contents": [{"role": "user", "parts": [{"text": "Cuantas calorias tiene una Big Mac segun McDonald's?"}]}],
                   "tools": [{"functionDeclarations": DECLS}, {"googleSearch": {}}],
                   "generationConfig": {"maxOutputTokens": 2048}}, key)
    if st == 200:
        print("OK (se pueden combinar)")
    else:
        print(f"NO se combinan (HTTP {st}) -> la app sigue sin busqueda, no se rompe")
        fallos.append("busqueda+herramientas (degrada solo)")

    print("\n" + "=" * 58)
    duros = [f for f in fallos if "degrada" not in f]
    if not duros:
        print("LISTO: el chat gratis con Gemini funciona de punta a punta.")
        if fallos: print("(unico detalle: " + fallos[0] + ")")
    else:
        print("HAY QUE ARREGLAR: " + ", ".join(duros))
    return 1 if duros else 0

if __name__ == "__main__":
    sys.exit(main())
