# -*- coding: utf-8 -*-
"""Mi Dia Nutricional — icono en la barra de notificaciones.

Arranca con Windows, en silencio: NO abre la app ni muestra ninguna ventana.
Solo deja el icono de la olla en la bandeja. Cuando querés cargar la comida,
un clic y se abre en Edge, en su propia ventana.

  clic en el icono        -> abre la app (version local, no depende de internet)
  boton derecho -> menu   -> abrir local / abrir la del celu (web) / salir

Se ejecuta SIEMPRE con pythonw.exe (sin consola). El .vbs de arranque se
encarga de eso. Consumo en reposo: practicamente cero, queda esperando eventos.

Log: logs\\bandeja_AAAA-MM-DD.txt (al lado de este archivo).
"""
import os
import sys
import ctypes
import subprocess
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
APP_LOCAL = AQUI / "index.html"
APP_WEB = "https://cdordanielegaston-art.github.io/mi-dia-nutricional/"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
ICONO_PNG = AQUI / "hot-pot-192.png"
ICONO_ICO = Path(r"D:\Datos Gaston\Desktop\Claude Code\hot-pot.ico")
MUTEX = "Global\\MiDiaNutricional_Bandeja_ECD"
CREATE_NO_WINDOW = 0x08000000


def log(msg):
    """Deja rastro en disco: sin consola, si algo falla no hay donde verlo."""
    try:
        d = AQUI / "logs"
        d.mkdir(exist_ok=True)
        linea = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n"
        with open(d / f"bandeja_{datetime.now():%Y-%m-%d}.txt", "a", encoding="utf-8") as f:
            f.write(linea)
    except Exception:
        pass


def instancia_unica():
    """Evita dos iconos si Windows lanza el arranque dos veces."""
    try:
        ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX)
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def abrir(destino):
    """Abre la app en Edge, en ventana propia (modo --app: sin barra de direcciones)."""
    try:
        if EDGE.exists():
            subprocess.Popen([str(EDGE), f"--app={destino}"], creationflags=CREATE_NO_WINDOW)
        else:
            webbrowser.open(destino)          # por si un dia mueven Edge
        log(f"abierta -> {destino}")
    except Exception as e:
        log(f"ERROR al abrir {destino}: {e}\n{traceback.format_exc()}")


def abrir_local(icon=None, item=None):
    abrir(APP_LOCAL.as_uri() if APP_LOCAL.exists() else APP_WEB)


def abrir_web(icon=None, item=None):
    abrir(APP_WEB)


def salir(icon, item=None):
    log("salir por menu")
    icon.stop()


def main():
    if not instancia_unica():
        log("ya habia una instancia corriendo, no arranco otra")
        return 0

    try:
        import pystray
        from PIL import Image
    except ImportError as e:
        log(f"faltan dependencias: {e}. Instalar con: pip install pystray pillow")
        return 1

    try:
        origen = ICONO_ICO if ICONO_ICO.exists() else ICONO_PNG
        img = Image.open(origen)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img.thumbnail((64, 64))
    except Exception as e:
        log(f"no pude cargar el icono ({e}), uso uno liso")
        from PIL import Image as I
        img = I.new("RGBA", (64, 64), (255, 140, 66, 255))

    menu = pystray.Menu(
        pystray.MenuItem("Abrir Mi Día Nutricional", abrir_local, default=True),
        pystray.MenuItem("Abrir la versión del celu (web)", abrir_web),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", salir),
    )
    icono = pystray.Icon("mi_dia_nutricional", img, "Mi Día Nutricional", menu)
    log("bandeja arriba (silenciosa, sin abrir la app)")
    try:
        icono.run()
    except Exception as e:
        log(f"ERROR en la bandeja: {e}\n{traceback.format_exc()}")
        return 1
    log("bandeja cerrada")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("ERROR fatal:\n" + traceback.format_exc())
        sys.exit(1)
