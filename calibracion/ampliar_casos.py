"""Amplia una corrida ya hecha con mas anclas por bin, sin repetir lo corrido.

Sortear de cero con mas anclas por bin da otro conjunto de casos: rng.choice sin reemplazo no
devuelve un prefijo estable al cambiar el tamaño (con 50 por bin solo 288 de los 1.215 casos de la
corrida 4 vuelven a salir). Como cada caso es independiente de los demas, ampliar es sumar casos
nuevos del mismo pool y con los mismos bins, y eso es lo que hace este paso:

1. Rehace el pool y la asignacion a bins de cada celda exactamente como paso0.py, con los mismos
   parametros de la corrida base (30 por bin), para que los bins sean los mismos.
2. En cada bin sortea N_EXTRA anclas entre las que NO salieron en la corrida base, con una seed
   propia: [SEED_SELECCION, nombre de la celda, "ampliacion"].
3. Escribe en el directorio nuevo el casos.csv completo (base + ampliacion), un
   casos_ampliacion.csv solo con los nuevos, y copia las trazas y recalls de la base para que el
   runner los saltee y corra solo lo nuevo.

Las celdas que en la base corrieron con menos anclas por bin (las tres flacas, a 5) se copian tal
cual: no tienen pool para mas.

Uso: CRECIMIENTO_RESULTADOS=<dir nuevo> CRECIMIENTO_BASE=<dir base> python ampliar_casos.py
"""
import os
import shutil

import numpy as np
import pandas as pd

from celdas import CELDAS, CELDAS_POR_PLANO, PLANOS, RESULTADOS, conectar, obtener_plano, \
    semillas_efectivas
from paso0 import BINS, SEED_SELECCION, con_control_construible, intentar_bins

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    os.environ.get("CRECIMIENTO_BASE", "resultados_corrida4"))
#anclas por bin con que se sorteo la base, para rehacer sus bins identicos
N_POR_BIN_BASE = 30
#anclas nuevas por bin que se suman
N_EXTRA = int(os.environ.get("CRECIMIENTO_N_EXTRA", "20"))


def sortear_ampliacion(asignacion, ya_elegidas, semillas_por_ancla, nombre_celda):
    """N_EXTRA anclas por bin entre las que no salieron en la base, con seed propia."""
    rng = np.random.default_rng([SEED_SELECCION, *nombre_celda.encode(), *b"ampliacion"])
    filas = []
    for nombre_bin in BINS:
        candidatas = sorted(a for a, b in asignacion.items()
                            if b == nombre_bin and a not in ya_elegidas)
        if len(candidatas) < N_EXTRA:
            raise ValueError(f"[{nombre_celda}] bin {nombre_bin}: quedan {len(candidatas)} "
                             f"anclas sin sortear para {N_EXTRA} lugares")
        for ancla in rng.choice(candidatas, size=N_EXTRA, replace=False):
            filas.append({"celda": nombre_celda, "ancla": ancla,
                          "n_semillas": len(semillas_por_ancla[ancla]),
                          "bin": nombre_bin, "seed": SEED_SELECCION})
    return pd.DataFrame(filas)


def main():
    os.makedirs(RESULTADOS, exist_ok=True)
    base = pd.read_csv(os.path.join(BASE, "casos.csv"))
    gds = conectar()
    nuevos = []

    for nombre_plano in PLANOS:
        red = None
        for nombre_celda in CELDAS_POR_PLANO[nombre_plano]:
            de_la_base = base[base["celda"] == nombre_celda]
            por_bin = de_la_base.groupby("bin").size()
            if de_la_base.empty or por_bin.min() < N_POR_BIN_BASE:
                print(f"[{nombre_celda}] se copia tal cual ({len(de_la_base)} casos, sin pool "
                      f"para ampliar)", flush=True)
                continue

            if red is None:
                red = obtener_plano(gds, PLANOS[nombre_plano], verbose=False)
            celda = CELDAS[nombre_celda]
            semillas = semillas_efectivas(gds, celda, red)
            n_candidatos = red.number_of_nodes() - (1 if celda.ancla_en_la_red else 0)
            semillas, _ = con_control_construible(semillas, n_candidatos)
            asignacion, motivo = intentar_bins(semillas, n_por_bin=N_POR_BIN_BASE)
            if asignacion is None:
                raise RuntimeError(f"[{nombre_celda}] la base tenia pool y ahora no: {motivo}")

            #control de que los bins rehechos son los de la base: cada ancla de la base tiene que
            #estar en el mismo bin
            for ancla, nombre_bin in zip(de_la_base["ancla"], de_la_base["bin"]):
                if asignacion.get(ancla) != nombre_bin:
                    raise RuntimeError(f"[{nombre_celda}] {ancla} estaba en el bin {nombre_bin} "
                                       f"y ahora cae en {asignacion.get(ancla)}")

            ampliacion = sortear_ampliacion(asignacion, set(de_la_base["ancla"]), semillas,
                                            nombre_celda)
            nuevos.append(ampliacion)
            print(f"[{nombre_celda}] {len(ampliacion)} casos nuevos sobre {len(de_la_base)} "
                  f"de la base", flush=True)

    ampliacion = pd.concat(nuevos)
    ampliacion.to_csv(os.path.join(RESULTADOS, "casos_ampliacion.csv"), index=False)
    pd.concat([base, ampliacion]).to_csv(os.path.join(RESULTADOS, "casos.csv"), index=False)

    #lo ya corrido se copia para que el runner lo saltee
    for carpeta in ("trazas", "recalls"):
        destino = os.path.join(RESULTADOS, carpeta)
        os.makedirs(destino, exist_ok=True)
        for archivo in os.listdir(os.path.join(BASE, carpeta)):
            if not os.path.exists(os.path.join(destino, archivo)):
                shutil.copy2(os.path.join(BASE, carpeta, archivo), destino)

    print(f"\nampliacion lista: {len(ampliacion)} casos nuevos, {len(base) + len(ampliacion)} "
          f"en total en {os.path.join(RESULTADOS, 'casos.csv')}")


if __name__ == "__main__":
    main()
