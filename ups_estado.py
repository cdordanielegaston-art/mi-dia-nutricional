# -*- coding: utf-8 -*-
r"""Lee la UPS de Gastón por USB y dice cómo está.

Windows NO la muestra como batería: el chip que trae (Cypress, VID 0665 / PID 5161)
es un puente serie disfrazado de HID, así que no aparece en la barra de tareas ni en
Win32_Battery. Pero habla el protocolo Megatec, que es texto plano.

Descubierto probando el 2026-08-19:
  · el comando de estado es **QS** (Q1, QGS y compañía solo devuelven eco)
  · F da los valores de fábrica
  · la respuesta llega DESPUÉS del eco del propio comando, hay que seguir escuchando

Uso:  python ups_estado.py
Requiere:  pip install hidapi
"""
import sys, io, time
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass
import hid

VID, PID = 0x0665, 0x5161


def _consultar(cmd, espera=3.5):
    d = hid.device()
    d.open(VID, PID)
    try:
        t0 = time.time()                       # vaciar lo que haya quedado
        while time.time() - t0 < 0.3:
            try:
                if not d.read(64, timeout_ms=60):
                    break
            except Exception:
                break
        b = (cmd + "\r").encode()
        for i in range(0, len(b), 8):          # el chip toma de a 8 bytes
            d.write(bytes([0]) + b[i:i + 8].ljust(8, b"\0"))
        crudo = b""
        fin = time.time() + espera
        while time.time() < fin:
            try:
                t = d.read(64, timeout_ms=200)
            except Exception:
                break
            if t:
                crudo += bytes(t)
            else:
                time.sleep(0.03)
        txt = crudo.replace(b"\x00", b"").decode("ascii", "replace")
        lineas = [l.strip() for l in txt.replace("\n", "\r").split("\r") if l.strip()]
        return [l for l in lineas if l != cmd]   # sacar el eco
    finally:
        try:
            d.close()
        except Exception:
            pass


def _num(x, defecto=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return defecto


def leer():
    """Devuelve un dict con lo que informa la UPS (None en lo que no reporte)."""
    info = {}

    for l in _consultar("F"):                  # nominales de fábrica
        if l.startswith("#"):
            p = l[1:].split()
            if len(p) >= 4:
                info["v_nominal"] = _num(p[0])
                info["a_nominal"] = _num(p[1])
                info["v_bateria_nominal"] = _num(p[2])
                info["hz_nominal"] = _num(p[3])
            break

    for l in _consultar("QS"):                 # estado actual
        if l.startswith("(") and len(l.split()) >= 7:
            p = l[1:].split()
            info["v_entrada"] = _num(p[0])
            info["v_salida"] = _num(p[2])
            info["carga_pct"] = _num(p[3])
            info["hz"] = _num(p[4])
            info["v_bateria"] = _num(p[5])
            info["temp"] = _num(p[6])          # varios modelos mandan "--.-"
            f = p[7] if len(p) > 7 else ""
            info["banderas"] = {
                "sin_luz": f[0] == "1" if len(f) > 0 else None,
                "bateria_baja": f[1] == "1" if len(f) > 1 else None,
                "regulando": f[2] == "1" if len(f) > 2 else None,
                "falla": f[3] == "1" if len(f) > 3 else None,
                "standby": f[4] == "1" if len(f) > 4 else None,
                "prueba": f[5] == "1" if len(f) > 5 else None,
                "chicharra": f[6] == "1" if len(f) > 6 else None,
            }
            info["crudo"] = l
            break
    return info


def _carga_bateria(v, nominal):
    """% aproximado por tensión en reposo (plomo-ácido 12 V)."""
    if not v or not nominal:
        return None
    v12 = v * 12.0 / nominal                   # normalizar a 12 V
    tabla = [(13.0, 100), (12.7, 100), (12.5, 90), (12.42, 75),
             (12.2, 50), (12.0, 25), (11.9, 10), (11.6, 0)]
    if v12 >= tabla[0][0]:
        return 100
    for (va, pa), (vb, pb) in zip(tabla, tabla[1:]):
        if va >= v12 >= vb:
            return int(pb + (v12 - vb) * (pa - pb) / (va - vb))
    return 0


def informe():
    i = leer()
    if not i:
        print("No pude leer la UPS. ¿Está encendida y con el cable USB puesto?")
        return 1

    va = (i.get("v_nominal") or 0) * (i.get("a_nominal") or 0)
    watts = va * 0.6                            # factor de potencia típico de estas UPS

    print("=" * 58)
    print("  UPS — lo que informa por USB")
    print("=" * 58)
    print(f"  Potencia nominal : {va:.0f} VA  (≈ {watts:.0f} W reales)")
    print(f"  Batería          : {i.get('v_bateria_nominal')} V nominales")
    print(f"  Tipo             : {'standby / offline' if (i.get('banderas') or {}).get('standby') else 'line-interactive'}")
    print()
    print(f"  Tensión de línea : {i.get('v_entrada')} V   (sale {i.get('v_salida')} V, {i.get('hz')} Hz)")
    carga = i.get("carga_pct")
    if carga is not None:
        print(f"  Carga conectada  : {carga:.0f} %"
              + (f"  ≈ {watts * carga / 100:.0f} W" if watts else "")
              + ("   <-- NO hay nada enchufado a la salida protegida" if carga == 0 else ""))
    vb = i.get("v_bateria")
    pct = _carga_bateria(vb, i.get("v_bateria_nominal"))
    print(f"  Batería          : {vb} V" + (f"  ≈ {pct}% de carga" if pct is not None else ""))
    if i.get("temp") is not None:
        print(f"  Temperatura      : {i['temp']} °C")

    b = i.get("banderas") or {}
    alertas = []
    if b.get("sin_luz"):      alertas.append("ESTÁ FUNCIONANDO A BATERÍA (se cortó la luz)")
    if b.get("bateria_baja"): alertas.append("BATERÍA BAJA")
    if b.get("falla"):        alertas.append("LA UPS REPORTA UNA FALLA")
    if b.get("regulando"):    alertas.append("está regulando la tensión (AVR activo)")
    print()
    print("  Estado           : " + ("; ".join(alertas) if alertas else "normal, con luz de red"))
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(informe())
