# -*- coding: utf-8 -*-
"""Deja el icono de Mi Dia Nutricional SIEMPRE VISIBLE en la barra de estado.

Windows 11 esconde los iconos nuevos adentro del desplegable "^". Para que uno
quede fijo hay que marcarlo como "promovido". Esto hace exactamente eso, que es
lo mismo que lograrias arrastrando el icono desde el "^" hasta la barra.

  python fijar_icono_barra.py            -> fija el de Mi Dia Nutricional
  python fijar_icono_barra.py --listar   -> muestra todos y cuales estan fijos
  python fijar_icono_barra.py "Ojos ECD" -> fija cualquier otro, por su tooltip

OJO: Windows recien crea la entrada del icono despues de que estuvo un rato en
la barra (a veces hasta el proximo inicio de sesion). Si dice que no lo encuentra,
no es un error: reinicia y corre esto de nuevo.

Toca solo HKEY_CURRENT_USER (tu usuario), y solo el valor IsPromoted. Reversible:
pasa el mismo tooltip con --soltar y vuelve a esconderse.
"""
import sys
import io
import winreg

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
RUTA = r"Control Panel\NotifyIconSettings"
POR_DEFECTO = "Mi Día Nutricional"


def leer_todos():
    """Devuelve [(subclave, tooltip, exe, promovido)] de todos los iconos."""
    salida = []
    try:
        base = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUTA)
    except FileNotFoundError:
        return salida
    for i in range(winreg.QueryInfoKey(base)[0]):
        sub = winreg.EnumKey(base, i)
        k = winreg.OpenKey(base, sub)
        d = {}
        for j in range(winreg.QueryInfoKey(k)[1]):
            nom, val, _ = winreg.EnumValue(k, j)
            d[nom] = val
        salida.append((sub,
                       str(d.get("InitialTooltip", "")),
                       str(d.get("ExecutablePath", "")).split("\\")[-1],
                       d.get("IsPromoted") == 1))
    return salida


def marcar(subclave, valor):
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUTA + "\\" + subclave, 0,
                       winreg.KEY_SET_VALUE)
    winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 1 if valor else 0)
    winreg.CloseKey(k)


def main():
    args = [a for a in sys.argv[1:]]
    soltar = "--soltar" in args
    args = [a for a in args if not a.startswith("--")]
    todos = leer_todos()

    if "--listar" in sys.argv[1:]:
        print(f"{'FIJO':5} {'EJECUTABLE':28} TOOLTIP")
        print("-" * 78)
        for _, tip, exe, prom in sorted(todos, key=lambda x: x[1].lower()):
            if tip:
                print(f"{'SI ' if prom else 'no ':5} {exe[:28]:28} {tip[:44]}")
        print(f"\n{sum(1 for t in todos if t[3])} fijados de {len(todos)}")
        return 0

    buscado = (args[0] if args else POR_DEFECTO)
    clave = buscado.lower().replace("í", "i").replace("á", "a").replace("é", "e").replace("ó", "o")
    candidatos = []
    for sub, tip, exe, prom in todos:
        t = tip.lower().replace("í", "i").replace("á", "a").replace("é", "e").replace("ó", "o")
        if clave in t:
            candidatos.append((sub, tip, exe, prom))

    if not candidatos:
        print(f"No encontré ningún icono que diga «{buscado}».")
        print("\nWindows todavía no guardó su entrada. Esto es normal si lo instalaste recién:")
        print("  1. Reiniciá la PC (o cerrá y volvé a abrir sesión).")
        print("  2. Corré este mismo archivo de nuevo.")
        print("\nAtajo que funciona siempre: clic en la flechita ^ de la barra y arrastrá")
        print("el ícono de la olla hasta la barra. Windows lo recuerda para siempre.")
        return 1

    for sub, tip, exe, prom in candidatos:
        objetivo = not soltar
        if prom == objetivo:
            print(f"«{tip}» ya está {'fijo' if prom else 'escondido'}. No toqué nada.")
            continue
        marcar(sub, objetivo)
        print(f"«{tip}» ({exe}) -> {'FIJO en la barra' if objetivo else 'escondido en el ^'}")
    print("\nSi no lo ves al toque, cerrá y volvé a abrir sesión (o reiniciá la barra de tareas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
