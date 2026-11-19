"""arma el indice de graphrag sobre el grafo entero, la linea de base de la evaluacion. se hace en tres pasos (exportar, proyecto e indexar)"""
#indexar se puede cortar y volver a lanzar: graphrag guarda cada reporte en su cache y no lo vuelve a pedir.
#proyecto e indexar llevan --con-texto para el indice de la evaluacion, que pone en las tablas el texto de cada nodo.
import argparse
import json
import os
import shutil
import sys
import time

import pandas as pd

#el ejecutable de graphrag es el que indique GRAPHRAG_BIN (ver .env.example en la raiz)
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..", "graphrag"))
sys.path.insert(0, os.path.join(AQUI, "..", "..", "manipulacion_grafo"))
sys.path.insert(0, os.path.join(AQUI, "..", "..", "seleccion_subgrafo"))
GRAFO_ENTERO = AQUI

from rag.graphrag_msft import (GRAPHRAG, configuracion_graphrag, escribir_proyecto, indexar, leer_textos,  # noqa: E402
                               nombre_de_corrida, tablas_desde, tokens_del_indice)


PARAMETROS = {"largo_reportes": 250, "largo_map": 200, "largo_respuesta": 400, "contexto_map": 5000,
              "tamano_comunidad": 20}

RUTA_NODOS = os.path.join(GRAFO_ENTERO, "nodos.parquet")
RUTA_ARISTAS = os.path.join(GRAFO_ENTERO, "aristas.parquet")


def exportar():
    #con las columnas de materializar_subgrafo, que es lo que espera tablas_desde
    from planos_y_pasos import conectar
    from subgrafo_query import LABELS
    gds = conectar()
    labels = sorted(LABELS)
    nodos = pd.concat([gds.run_cypher(f"MATCH (n:{label}) RETURN '{label}' AS label, n.id AS id, n.name AS nombre")
                       for label in labels], ignore_index=True)
    #un nodo sin nombre se muestra por su id
    nodos["nombre"] = nodos["nombre"].fillna(nodos["id"])
    assert nodos["id"].is_unique, "hay ids repetidos entre labels"

    tipos = gds.run_cypher("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType AS tipo")["tipo"]
    partes = []
    for tipo in tipos:
        #un tipo a la vez, para no traer todo en una sola respuesta. el filtro deja afuera las aristas con un
        #extremo fuera del alcance de la seleccion (Pathway)
        partes.append(gds.run_cypher(
            f"MATCH (a)-[r:{tipo}]->(b) WHERE labels(a)[0] IN $labels AND labels(b)[0] IN $labels "
            f"RETURN labels(a)[0] AS label_a, a.id AS id_a, labels(b)[0] AS label_b, b.id AS id_b, '{tipo}' AS tipo",
            params={"labels": labels}))
        print(f"[exportar] {tipo}: {len(partes[-1]):,} aristas", flush=True)
    aristas = pd.concat(partes, ignore_index=True)

    os.makedirs(GRAFO_ENTERO, exist_ok=True)
    nodos.to_parquet(RUTA_NODOS, index=False)
    aristas.to_parquet(RUTA_ARISTAS, index=False)
    print(f"[exportar] {len(nodos):,} nodos y {len(aristas):,} aristas")


def armar_proyecto(raiz, parametros):
    if not os.path.exists(RUTA_ARISTAS):
        print("falta exportar el grafo entero (paso exportar, con neo4j-thesis levantado)")
        return 1
    #se puede volver a armar sin perder la cache/ de un indice empezado
    #con --con-texto, el texto de PrimeKG de cada nodo entra a las tablas, igual que en los subgrafos de la seleccion
    textos = leer_textos() if parametros.get("con_texto") else None
    entities, relationships, text_units = tablas_desde(pd.read_parquet(RUTA_NODOS), pd.read_parquet(RUTA_ARISTAS), textos)
    escribir_proyecto(raiz, entities, relationships, text_units, configuracion_graphrag(parametros=parametros))
    print(f"[proyecto] {len(entities):,} entidades y {len(relationships):,} relaciones en {raiz}")
    return 0


def indexar_grafo_entero(raiz):
    carpeta = os.path.dirname(raiz)
    if os.path.exists(os.path.join(raiz, "output", "community_reports.parquet")):
        print(f"el indice ya esta en {raiz}")
        return 0
    if not os.path.exists(os.path.join(raiz, "output", "entities.parquet")):
        print(f"falta el proyecto en {raiz} (paso proyecto, en la laptop)")
        return 1
    #el tiempo total cuenta desde el primer intento, no solo el ultimo
    ruta_inicio = os.path.join(carpeta, "inicio")
    if not os.path.exists(ruta_inicio):
        with open(ruta_inicio, "w") as archivo:
            archivo.write(str(time.time()))
    with open(ruta_inicio) as archivo:
        inicio = float(archivo.read())

    codigo, segundos, cola = indexar(raiz)
    print(f"[indexar] codigo {codigo} en {segundos:.0f} s", flush=True)
    if codigo != 0:
        print(cola)
        return codigo

    comunidades = pd.read_parquet(os.path.join(raiz, "output", "communities.parquet"))
    reportes = pd.read_parquet(os.path.join(raiz, "output", "community_reports.parquet"))
    #graphrag descarta los reportes con JSON invalido despues de los reintentos: quedan comunidades sin reporte
    sin_reporte = comunidades[~comunidades["community"].isin(reportes["community"])]
    indice = {"codigo": codigo, "segundos_total": round(time.time() - inicio, 1), "segundos_ultimo_intento": segundos,
              "comunidades": len(comunidades),
              "comunidades_por_nivel": {int(n): int(c) for n, c in comunidades["level"].value_counts().sort_index().items()},
              "reportes": len(reportes), "sin_reporte": len(sin_reporte),
              "sin_reporte_por_nivel": {int(n): int(c) for n, c in sin_reporte["level"].value_counts().sort_index().items()},
              "salida": cola, **tokens_del_indice(raiz)}
    with open(os.path.join(carpeta, "indice.json"), "w") as archivo:
        json.dump(indice, archivo, indent=1)
    print(f"[indexar] {indice['reportes']:,} reportes de {indice['comunidades']:,} comunidades, "
          f"{indice['llamadas_indice']:,} llamadas al modelo")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paso", choices=("exportar", "proyecto", "indexar"))
    parser.add_argument("--con-texto", action="store_true", help="el texto de cada nodo entra a las tablas de graphrag")
    argumentos = parser.parse_args()
    parametros = {**PARAMETROS, "con_texto": argumentos.con_texto}
    raiz = os.path.join(GRAFO_ENTERO, nombre_de_corrida(parametros), "graphrag")
    if argumentos.paso == "exportar":
        exportar()
    elif argumentos.paso == "proyecto":
        sys.exit(armar_proyecto(raiz, parametros))
    else:
        assert shutil.which(GRAPHRAG), f"no esta el ejecutable de graphrag en {GRAPHRAG}: fijar GRAPHRAG_BIN"
        #codigo de salida distinto de cero si fallo, para relanzar hasta que termine
        sys.exit(1 if indexar_grafo_entero(raiz) else 0)


if __name__ == "__main__":
    main()
