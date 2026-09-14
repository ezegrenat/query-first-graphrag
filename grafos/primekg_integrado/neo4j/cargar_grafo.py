"""Carga PrimeKG integrado (los CSV de datos/processed/) al contenedor neo4j-thesis.

Uso, con el contenedor levantado (docker start neo4j-thesis):
    python cargar_grafo.py


Que se carga:
- Todos los nodos, con label por tipo (LABEL_POR_TIPO) y propiedades id, name, node_index y
  source. Los nodos Disease llevan ademas es_grupo_bert y los Gene es_complejo_signor, para que
  quien consulte pueda dejarlos afuera sin adivinar por el formato del id.
- Cada arista una sola vez. El CSV de origen guarda cada arista en los dos sentidos; se verifica
  que sea asi y se conserva la fila con x_index < y_index. El sentido en Neo4j es arbitrario:
  todo el grafo es no dirigido y el experimento lo lee con -[r]- sin flecha.
- disease_disease se parte en DISEASE_DISEASE (padre-hijo de MONDO) y DISEASE_BERT (la estrella
  que une cada grupo BERT con sus miembros, listada en disease_bert_edges.csv).
"""
import sys
import time
from datetime import datetime

import pandas as pd
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, TransientError

from config import (ARCHIVO_ARISTAS, ARCHIVO_ESTRELLAS, ARCHIVO_NODOS, BATCH_SIZE, LABEL_POR_TIPO,
                    MAX_REINTENTOS, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, RELACION_ESTRELLA,
                    RELACION_POR_TIPO)

_inicio = time.perf_counter()


def log(mensaje):
    hora = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora} | +{time.perf_counter() - _inicio:7.1f}s] {mensaje}", flush=True)


def conectar():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except (ServiceUnavailable, OSError) as error:
        print(f"No se pudo conectar a {NEO4J_URI}. Probar:\n"
              "  sudo systemctl start docker\n"
              "  docker start neo4j-thesis   (o bash crear_contenedor.sh si no existe)\n"
              f"Detalle: {error}")
        sys.exit(1)
    log(f"conectado a {NEO4J_URI}")
    return driver


def con_reintentos(session, consulta, filas):
    for intento in range(MAX_REINTENTOS):
        try:
            return session.run(consulta, rows=filas).consume()
        except TransientError:
            if intento == MAX_REINTENTOS - 1:
                raise
            time.sleep(2 ** intento)


def lotes(registros, tamano=BATCH_SIZE):
    for desde in range(0, len(registros), tamano):
        yield registros[desde:desde + tamano]


def leer_nodos():
    nodos = pd.read_csv(ARCHIVO_NODOS, dtype={"node_id": str})
    #se lee como texto para no perder ids como "8702_10966" ni convertir Entrez a numero
    nodos["es_grupo_bert"] = (nodos.node_type == "disease") & (nodos.node_source == "primekg")
    nodos["es_complejo_signor"] = nodos.node_id.str.startswith("SIGNOR")
    return nodos


def leer_aristas():
    """Una fila por arista, con el tipo de relacion de Neo4j ya decidido."""
    filas = pd.read_csv(ARCHIVO_ARISTAS)
    pares = set(zip(filas.x_index, filas.y_index))
    sin_inversa = sum((b, a) not in pares for a, b in pares)
    if sin_inversa:
        raise ValueError(f"{sin_inversa} filas del CSV no tienen su inversa; se esperaba que "
                         "cada arista estuviera en los dos sentidos")
    aristas = filas[filas.x_index < filas.y_index].copy()

    estrellas = pd.read_csv(ARCHIVO_ESTRELLAS)
    pares_estrella = set(zip(estrellas.x_index, estrellas.y_index))
    es_estrella = [(a, b) in pares_estrella or (b, a) in pares_estrella
                   for a, b in zip(aristas.x_index, aristas.y_index)]
    aristas["relacion"] = aristas.edge_type.map(RELACION_POR_TIPO)
    aristas.loc[es_estrella, "relacion"] = RELACION_ESTRELLA
    if aristas.relacion.isna().any():
        raise ValueError(f"edge_type sin relacion asignada: "
                         f"{aristas[aristas.relacion.isna()].edge_type.unique()}")
    return aristas


def crear_restricciones(driver):
    with driver.session() as session:
        for tipo, label in LABEL_POR_TIPO.items():
            session.run(f"CREATE CONSTRAINT restriccion_{tipo} IF NOT EXISTS "
                        f"FOR (n:{label}) REQUIRE n.node_index IS UNIQUE")
        activas = {r["name"] for r in session.run("SHOW CONSTRAINTS").data()}
    faltan = {f"restriccion_{tipo}" for tipo in LABEL_POR_TIPO} - activas
    if faltan:
        raise RuntimeError(f"restricciones que no quedaron activas: {faltan}")
    log(f"restricciones de unicidad sobre node_index activas para {list(LABEL_POR_TIPO.values())}")


def cargar_nodos(driver, nodos):
    #el MERGE es por node_index y no por id: en el CSV de origen node_index es unico y entero,
    #mientras que node_id es texto mezclado. Las consultas del experimento pueden usar cualquiera
    with driver.session() as session:
        for tipo, label in LABEL_POR_TIPO.items():
            del_tipo = nodos[nodos.node_type == tipo]
            registros = [
                {"node_index": int(f.node_index), "id": f.node_id, "name": f.node_name,
                 "source": f.node_source, "es_grupo_bert": bool(f.es_grupo_bert),
                 "es_complejo_signor": bool(f.es_complejo_signor)}
                for f in del_tipo.itertuples()
            ]
            for lote in lotes(registros):
                con_reintentos(
                    session,
                    f"UNWIND $rows AS row "
                    f"MERGE (n:{label} {{node_index: row.node_index}}) "
                    "SET n.id = row.id, n.name = row.name, n.source = row.source, "
                    "n.es_grupo_bert = row.es_grupo_bert, n.es_complejo_signor = row.es_complejo_signor",
                    lote)
            log(f"  {label}: {len(registros)} nodos")


def cargar_aristas(driver, aristas, nodos):
    label_por_indice = nodos.set_index("node_index").node_type.map(LABEL_POR_TIPO)
    with driver.session() as session:
        for relacion, del_tipo in aristas.groupby("relacion"):
            #las etiquetas de los dos extremos van en el MATCH para que use las restricciones;
            #dentro de una relacion los tipos de extremo son siempre los mismos
            label_a = label_por_indice[del_tipo.x_index.iloc[0]]
            label_b = label_por_indice[del_tipo.y_index.iloc[0]]
            registros = [
                {"a": int(f.x_index), "b": int(f.y_index), "source": f.edge_source}
                for f in del_tipo.itertuples()
            ]
            cargadas = 0
            for lote in lotes(registros):
                con_reintentos(
                    session,
                    f"UNWIND $rows AS row "
                    f"MATCH (a:{label_a} {{node_index: row.a}}) "
                    f"MATCH (b:{label_b} {{node_index: row.b}}) "
                    f"MERGE (a)-[r:{relacion}]->(b) SET r.source = row.source",
                    lote)
                cargadas += len(lote)
            log(f"  {relacion} ({label_a} a {label_b}): {cargadas} aristas")


def main():
    nodos = leer_nodos()
    aristas = leer_aristas()
    log(f"leidos {len(nodos)} nodos y {len(aristas)} aristas del CSV de origen")
    print(aristas.relacion.value_counts().to_string())

    driver = conectar()
    try:
        crear_restricciones(driver)
        cargar_nodos(driver, nodos)
        cargar_aristas(driver, aristas, nodos)
        log("carga terminada; correr verificar_carga.py")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
