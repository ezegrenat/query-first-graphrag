"""Carga de dos corridas pareadas para compararlas en un notebook.

Existe para `comparar_inclusion_bert.ipynb`, que compara correr DIAMOnD en el plano de
enfermedades con y sin los grupos BERT. Las dos corridas usan las mismas anclas y los mismos
bins, asi que la misma consulta se puede seguir sobre dos redes. No supone nada de los grupos:
recibe {etiqueta: carpeta de resultados} y sirve para cualquier par de corridas pareadas.

Es solo la capa de datos; los graficos viven en el notebook. Lo que hace y `graficos.py` no es
leer dos carpetas en el mismo proceso: sus cargadores estan atados a la carpeta del modulo
(`RESULTADOS`, via la variable de entorno). El arrastre de las corridas truncadas y el relleno de
los folds ausentes se importan de ahi, para que los promedios den lo mismo que los PDF por plano
y que resumen_celdas.csv.
"""
import os

import pandas as pd

#graficos fija el backend Agg al importarse: en un notebook hay que volver al inline despues
from graficos import arrastrar_hasta_el_presupuesto, completar_folds_ausentes
from celdas import CELDAS
from runner import _ruta

_AQUI = os.path.dirname(os.path.abspath(__file__))

#los nodos del grafo, para saber cuales son grupos BERT sin levantar Neo4j. Es el mismo
#conjunto que celdas.nodos_que_no_pueden_ser_semilla saca del contenedor con es_grupo_bert
NODOS_CRUDOS = os.path.join(_AQUI, "..", "grafos", "primekg_integrado", "datos", "processed",
                            "merged_nodes.csv")


def cargar_version(carpeta, celda_nombre):
    """(trazas, recalls) de una carpeta de resultados, con el mismo tratamiento que los PDF.

    Las anclas salen de casos.csv y no de los nombres de archivo del directorio: la lista de
    casos manda y el disco solo confirma, asi que un parquet suelto de otra corrida no entra.
    """
    celda = CELDAS[celda_nombre]
    #dtype=str porque las anclas de las celdas con origen Gene son numeros de Entrez y _ruta las
    #trata como texto. Hoy casos.csv mezcla CUIs y numeros y pandas ya infiere texto, pero eso
    #depende de que el archivo traiga las dos celdas
    casos = pd.read_csv(os.path.join(carpeta, "casos.csv"), dtype={"ancla": str})
    casos = casos[casos["celda"] == celda_nombre]
    dir_trazas = os.path.join(carpeta, "trazas")
    dir_recalls = os.path.join(carpeta, "recalls")
    casos = casos[[os.path.exists(_ruta(dir_trazas, celda, a))
                   and os.path.exists(_ruta(dir_recalls, celda, a)) for a in casos["ancla"]]]
    if casos.empty:
        raise ValueError(f"{carpeta}: ningun caso de {celda_nombre} tiene sus dos parquet")

    def _apilar(directorio):
        partes = []
        for _, fila in casos.iterrows():
            tabla = pd.read_parquet(_ruta(directorio, celda, fila["ancla"]))
            tabla["ancla"] = fila["ancla"]
            tabla["bin"] = fila["bin"]
            partes.append(tabla)
        return pd.concat(partes, ignore_index=True)

    trazas = arrastrar_hasta_el_presupuesto(_apilar(dir_trazas), "iteracion",
                                            ("nodo", "grado", "kb"))
    recalls = arrastrar_hasta_el_presupuesto(_apilar(dir_recalls), "rank", ())
    return trazas, completar_folds_ausentes(recalls)


def cargar(ramas, celda_nombre):
    """{etiqueta: (trazas, recalls)} para {etiqueta: carpeta}, en el orden en que vienen."""
    return {etiqueta: cargar_version(carpeta, celda_nombre)
            for etiqueta, carpeta in ramas.items()}


def ids_de_grupos_bert(ruta=NODOS_CRUDOS):
    """Los ids de los 1.040 grupos BERT, para reconocerlos entre los nodos que agrega DIAMOnD.

    Salen del CSV de nodos del grafo (los `disease` cuya fuente es primekg) y no de Neo4j, asi el
    notebook no necesita el contenedor levantado. Verificado contra los planos en cache: los 1.040
    estan en el plano con grupos y ninguno en el plano sin grupos.
    """
    nodos = pd.read_csv(ruta, dtype=str)
    grupos = nodos[(nodos["node_type"] == "disease") & (nodos["node_source"] == "primekg")]
    return frozenset(grupos["node_id"])
