"""Smoke run previo al batch: un caso por celda, para medir el costo antes de gastarlo.

Corre el pipeline completo de un caso de cada celda (la corrida real, sus controles y sus folds
de recall) y reporta cuanto tardo cada uno. Con eso estima el batch entero de dos maneras: el
total si se corriera en un solo proceso, y el maximo por plano, que es lo que realmente tarda
cuando se lanza un proceso por plano.

Los casos que corre quedan escritos en disco como cualquier otro, asi que el batch posterior los
saltea en vez de repetirlos.
"""
import os
import time

import pandas as pd

from celdas import CELDAS, ORDEN_CELDAS, PLANOS, RESULTADOS, conectar, obtener_plano, \
    semillas_efectivas
from paso0_sorteo import BINS
from paso2_runner import correr_caso


def un_caso_por_celda(casos):
    """Un caso por celda, del bin medio: ni el mas chico ni el mas grande de la celda."""
    elegidos = []
    for _, del_celda in casos.groupby("celda", sort=False):
        del_medio = del_celda[del_celda["bin"] == BINS[1]]
        elegidos.append((del_medio if not del_medio.empty else del_celda).iloc[0])
    return pd.DataFrame(elegidos)


def main():
    ruta_casos = os.path.join(RESULTADOS, "casos.csv")
    if not os.path.exists(ruta_casos):
        raise SystemExit(f"falta {ruta_casos}: correr paso0_sorteo.py antes del smoke")
    todos = pd.read_csv(ruta_casos)
    casos = un_caso_por_celda(todos)

    gds = conectar()
    planos_cargados = {}
    filas = []
    for nombre_celda in ORDEN_CELDAS:
        del_celda = casos[casos["celda"] == nombre_celda]
        if del_celda.empty:
            continue
        celda = CELDAS[nombre_celda]
        if celda.plano not in planos_cargados:
            planos_cargados[celda.plano] = obtener_plano(gds, PLANOS[celda.plano], verbose=False)
        red = planos_cargados[celda.plano]
        semillas = semillas_efectivas(gds, celda, red)

        ancla = del_celda.iloc[0]["ancla"]
        t0 = time.time()
        correr_caso(celda, ancla, semillas[ancla], red)
        segundos = time.time() - t0
        registro = {"celda": nombre_celda, "plano": celda.plano, "ancla": ancla,
                    "n_semillas": len(semillas[ancla]),
                    "nodos_plano": red.number_of_nodes(),
                    "aristas_plano": red.number_of_edges(),
                    "segundos": round(segundos, 1),
                    "casos_de_la_celda": int((todos["celda"] == nombre_celda).sum())}
        filas.append(registro)
        print(registro, flush=True)

    tabla = pd.DataFrame(filas)
    print()
    print(tabla.to_string(index=False))

    tabla["horas_de_la_celda"] = tabla["segundos"] * tabla["casos_de_la_celda"] / 3600
    total = tabla["horas_de_la_celda"].sum()
    por_plano = tabla.groupby("plano")["horas_de_la_celda"].sum()
    print()
    print("costo estimado del batch, por plano:")
    for plano, horas in por_plano.items():
        print(f"  {plano:12s} {horas:6.1f}h")
    print(f"\ntotal en un solo proceso: {total:.1f}h")
    print(f"con un proceso por plano, la ruta critica es {por_plano.idxmax()}: "
          f"{por_plano.max():.1f}h")


if __name__ == "__main__":
    main()
