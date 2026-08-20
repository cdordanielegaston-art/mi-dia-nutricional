# -*- coding: utf-8 -*-
r"""Prueba REAL de la batería de la UPS: mide cuánto aguanta con la luz cortada.

Por qué hace falta: enchufada a la pared, la batería marca 13,5 V aunque esté
sulfatada — el cargador la sostiene. Lo único que dice la verdad es cortarle la
luz y ver cuánto dura y cómo se desploma la tensión.

Cómo se usa:
  1. Enchufá algo a los tomas que dicen "Battery Backup" (un monitor, una lámpara,
     la PC). Sin carga la prueba no mide nada: la UPS aguantaría horas de gusto.
  2. Arrancá este script.
  3. Cuando te lo pida, DESENCHUFÁ la UPS de la pared.
  4. Dejalo correr. Volvé a enchufar cuando el script te avise (o cuando quieras
     cortar; con llegar a ~11,5 V ya alcanza para saber).

Al final dice: minutos aguantados, con cuánta carga, y si la batería está sana,
gastada o para tirar.
"""
import sys, io, time, csv
from datetime import datetime
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from ups_estado import leer   # reusa el lector ya probado

INTERVALO = 5          # segundos entre lecturas
V_CORTE   = 10.8       # por debajo de esto la UPS se apaga sola


def barra(pct, ancho=22):
    n = max(0, min(ancho, int(round(pct / 100 * ancho))))
    return "█" * n + "·" * (ancho - n)


def main():
    i = leer()
    if not i:
        print("No pude leer la UPS. ¿Está encendida y con el cable USB puesto?")
        return 1

    va = (i.get("v_nominal") or 0) * (i.get("a_nominal") or 0)
    watts_max = va * 0.6
    carga0 = i.get("carga_pct") or 0

    print("=" * 62)
    print("  PRUEBA DE BATERÍA — cuánto aguanta con la luz cortada")
    print("=" * 62)
    print(f"  UPS            : {va:.0f} VA (≈{watts_max:.0f} W)")
    print(f"  Carga ahora    : {carga0:.0f} %  ≈ {watts_max*carga0/100:.0f} W")
    print(f"  Batería ahora  : {i.get('v_bateria')} V")
    print()

    if carga0 == 0:
        print("  ⚠ NO hay nada enchufado en la salida con batería.")
        print("    Enchufá algo (monitor, lámpara, la PC) en los tomas que dicen")
        print("    'Battery Backup' y volvé a correr esto. Sin carga la prueba no")
        print("    mide nada: aguantaría muchísimo y no sabrías si la batería sirve.")
        return 2

    print("  Cuando quieras: DESENCHUFÁ LA UPS DE LA PARED.")
    print("  (esperando…  Ctrl+C para cancelar)")
    print()

    registro = []
    t_corte = None
    v_inicial = None
    ultimo_aviso = 0

    try:
        while True:
            i = leer()
            if not i:
                time.sleep(INTERVALO)
                continue
            sin_luz = (i.get("banderas") or {}).get("sin_luz")
            vb = i.get("v_bateria") or 0
            carga = i.get("carga_pct") or 0
            ahora = time.time()

            if sin_luz and t_corte is None:
                t_corte = ahora
                v_inicial = vb
                print(f"  ⚡ SE CORTÓ LA LUZ — arranca la cuenta")
                print(f"     batería {vb} V · carga {carga:.0f}% "
                      f"(≈{watts_max*carga/100:.0f} W)")
                print()
                print(f"     {'min':>6}  {'batería':>8}  {'carga':>6}   estado")
                print("     " + "-" * 46)

            if t_corte:
                mins = (ahora - t_corte) / 60
                registro.append((round(mins, 2), vb, carga))
                # % aproximado entre la tensión inicial y el corte
                pct = max(0, min(100, (vb - V_CORTE) / max(0.1, (v_inicial - V_CORTE)) * 100))
                print(f"     {mins:6.1f}  {vb:7.2f}V  {carga:5.0f}%   {barra(pct)}")

                if not sin_luz:
                    print()
                    print("  🔌 Volvió la luz — prueba terminada.")
                    break
                if (i.get("banderas") or {}).get("bateria_baja"):
                    print("     ⚠ la UPS avisa BATERÍA BAJA")
                if vb <= V_CORTE:
                    print()
                    print("  🪫 Llegó al voltaje de corte.")
                    break
            else:
                if ahora - ultimo_aviso > 20:
                    print(f"  … con luz de red (batería {vb} V). Desenchufá cuando quieras.")
                    ultimo_aviso = ahora

            time.sleep(INTERVALO)
    except KeyboardInterrupt:
        print("\n  (cancelado a mano)")

    if not registro:
        print("\n  No se llegó a medir nada: nunca se cortó la luz.")
        return 3

    # ── veredicto ──
    mins = registro[-1][0]
    carga_prom = sum(r[2] for r in registro) / len(registro)
    w = watts_max * carga_prom / 100
    v_fin = registro[-1][1]
    caida = (v_inicial - v_fin) / max(0.01, mins)      # V por minuto

    print()
    print("=" * 62)
    print("  RESULTADO")
    print("=" * 62)
    print(f"  Aguantó            : {mins:.1f} minutos")
    print(f"  Con una carga de   : {carga_prom:.0f} %  ≈ {w:.0f} W")
    print(f"  Batería: {v_inicial:.2f} V → {v_fin:.2f} V  (cae {caida:.2f} V por minuto)")
    print()

    # Regla práctica para una batería de 12 V / 7-9 Ah
    if w > 0:
        esperado = (7 * 12 * 0.5) / w * 60 * 0.7   # ~50% útil, 70% de eficiencia
        print(f"  Una batería sana daría ≈ {esperado:.0f} min con esa carga.")
        if mins >= esperado * 0.75:
            print("  ✅ La batería está BIEN.")
        elif mins >= esperado * 0.4:
            print("  ⚠ Batería GASTADA: sirve para un corte corto, no para confiarle un servidor.")
        else:
            print("  ❌ Batería AGOTADA: hay que cambiarla (son baratas y se cambian solas).")
    print()
    print(f"  Con {w:.0f} W aguantó {mins:.1f} min. Para otra carga, la autonomía")
    print(f"  baja más o menos en proporción inversa.")

    # dejar el detalle por si se quiere mirar después
    salida = f"ups_prueba_{datetime.now():%Y-%m-%d_%H%M}.csv"
    with open(salida, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["minutos", "v_bateria", "carga_pct"])
        wr.writerows(registro)
    print(f"\n  Detalle guardado en: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
