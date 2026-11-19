#la tabla que arma tablas.ipynb en cada seccion: media por configuracion y diferencia apareada con su intervalo
import os

import numpy as np
import pandas as pd

#las tablas quedan en salidas/
os.makedirs("salidas", exist_ok=True)

CONFIGURACIONES = ["sin_grafo", "grafo_entero", "semillas", "diamond", "diamond_c3", "completa"]
SELECCION = ["semillas", "diamond", "diamond_c3", "completa"]
NOMBRES = {"sin_grafo": "modelo solo", "grafo_entero": "grafo entero", "semillas": "solo semillas", "diamond": "DIAMOnD",
           "diamond_c3": "DIAMOnD y C3", "completa": "completa"}
REMUESTREOS = 10000


def intervalo(diferencias):
    """intervalo del 95 % de la diferencia promedio. se sortean preguntas con reposicion, se promedia cada sorteo y luego se toman los percentiles 2,5 y 97,5. REcibe un vector con una diferencia por pregunta y devuelve los dos extremos dle intervlao"""
    generador = np.random.default_rng(42)
    sorteos = generador.integers(0, len(diferencias), size=(REMUESTREOS, len(diferencias)))
    medias = diferencias[sorteos].mean(axis=1)
    return np.percentile(medias, [2.5, 97.5])


def comparar(por_pregunta):
    """recibe una fila por pregunta y una columna por configuracion con las repeticiones ya promediadas y arma la tabla final. solo cuentan las preguntas que tienen a las seis configuraciones."""
    por_pregunta = por_pregunta.dropna()
    filas = []
    for configuracion in CONFIGURACIONES:
        fila = {"configuracion": NOMBRES[configuracion], "preguntas": len(por_pregunta), "media": por_pregunta[configuracion].mean()}
        for referencia, nombre in [("sin_grafo", "solo"), ("grafo_entero", "entero")]:
            if configuracion != referencia:
                diferencias = (por_pregunta[configuracion] - por_pregunta[referencia]).to_numpy()
                desde, hasta = intervalo(diferencias)
                fila[f"menos {nombre}"] = diferencias.mean()
                fila[f"{nombre} desde"] = desde
                fila[f"{nombre} hasta"] = hasta
        filas.append(fila)
    columnas = ["preguntas", "media", "menos solo", "solo desde", "solo hasta", "menos entero", "entero desde", "entero hasta"]
    return pd.DataFrame(filas).set_index("configuracion")[columnas].round(3)


def interaccion(adentro, afuera):
    """recibe dos tablas (una por cada grupo de preguntas) y calcula  cuanto cambia la diferencia contra el modelo solo entre dos grupos de preguntas. Cada grupo se remuestrea por su lado. el grafo entero no depend del subgrafo, asi que sirve de control"""
    filas = []
    for configuracion in CONFIGURACIONES[1:]:
        de_adentro = (adentro[configuracion] - adentro["sin_grafo"]).to_numpy()
        de_afuera = (afuera[configuracion] - afuera["sin_grafo"]).to_numpy()
        generador = np.random.default_rng(42)
        sorteos_adentro = generador.integers(0, len(de_adentro), size=(REMUESTREOS, len(de_adentro)))
        sorteos_afuera = generador.integers(0, len(de_afuera), size=(REMUESTREOS, len(de_afuera)))
        medias = de_adentro[sorteos_adentro].mean(axis=1) - de_afuera[sorteos_afuera].mean(axis=1)
        desde, hasta = np.percentile(medias, [2.5, 97.5])
        filas.append({"configuracion": NOMBRES[configuracion], "interaccion": de_adentro.mean() - de_afuera.mean(),
                      "desde": desde, "hasta": hasta})
    return pd.DataFrame(filas).set_index("configuracion").round(3)


def con_respaldo(medidas, medida):
    "una fila por pregunta, donde la pregunta con subgrafo vacio vale lo mismo que el modelo solo en vez de abstenerse"
    por_pregunta = medidas.pivot_table(index="consulta", columns="configuracion", values=medida)[CONFIGURACIONES]
    abstiene = medidas.pivot_table(index="consulta", columns="configuracion", values="abstiene")
    for configuracion in SELECCION:
        por_pregunta[configuracion] = por_pregunta[configuracion].where(abstiene[configuracion] == 0, por_pregunta["sin_grafo"])
    return por_pregunta
