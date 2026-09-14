"""Carga el grafo OptimusKG (parquet local) a Neo4j.

Uso:
    python loader/load_neo4j.py

Requiere un Neo4j corriendo y accesible con las credenciales del .env, y las dependencias de
requirements.txt instaladas.

Es idempotente: usa MERGE tanto para nodos como para relaciones, así que si se corta a mitad de
camino se puede volver a correr sin duplicar datos (vuelve a pasar por los tipos ya cargados, pero
no crea nada de nuevo para lo que ya estaba).
"""

import json
import sys
import time
from datetime import datetime

import optimuskg as okg
import pyarrow as pa
import pyarrow.parquet as pq
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable, TransientError

from config import (
    BATCH_SIZE,
    CAMPOS_EXCLUIR,
    EDGE_TYPE_NODE_TYPES,
    EDGE_TYPES,
    MAX_REINTENTOS,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    NODE_TYPES,
    label_de,
)


_inicio_pipeline = time.perf_counter()


def log(mensaje):
    """Imprime con hora y tiempo transcurrido desde que arrancó la carga, más útil que un print
    suelto para seguir una carga larga (potencialmente horas) y ver en qué paso se frenó si algo
    se cuelga."""
    transcurrido = time.perf_counter() - _inicio_pipeline
    hora = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora} | +{transcurrido:8.1f}s] {mensaje}")


def connect():
    """Conecta al contenedor Neo4j. Si no puede, explica el motivo más probable y corta."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except (ServiceUnavailable, OSError) as e:
        print(f"No se pudo conectar a Neo4j en {NEO4J_URI}.\n"
              f"Revisar que el contenedor esté corriendo (docker ps) y que las credenciales\n"
              f"del .env sean las de esa base.\n"
              f"Detalle del error: {e}")
        sys.exit(1)
    log(f"Conectado a Neo4j en {NEO4J_URI}")
    return driver


def crear_restricciones(driver):
    """Crea una restricción de unicidad sobre `id` por cada tipo de nodo (necesario para que
    MERGE sea rápido con millones de filas; sin índice, cada MERGE escanea toda la etiqueta).

    Le ponemos nombre explícito a cada restricción (en vez de dejar que Neo4j autogenere uno) para
    poder identificarlas fácil después en `SHOW CONSTRAINTS` o si hay que borrarlas.
    """
    with driver.session() as session:
        for tipo in NODE_TYPES:
            label = label_de(tipo)
            nombre = f"restriccion_{tipo}"
            session.run(
                f"CREATE CONSTRAINT {nombre} IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )
        log(f"Restricciones de unicidad creadas para {len(NODE_TYPES)} tipos de nodo")

        #verificacion: confirmar que las 10 restricciones quedaron activas antes de seguir.
        registros = session.run("SHOW CONSTRAINTS").data()
        nombres_creados = {r["name"] for r in registros}
        nombres_esperados = {f"restriccion_{tipo}" for tipo in NODE_TYPES}
        faltantes = nombres_esperados - nombres_creados
        if faltantes:
            log(f"ADVERTENCIA: no se encontraron estas restricciones tras crearlas: {faltantes}")
        else:
            log(f"Verificado con SHOW CONSTRAINTS: las {len(NODE_TYPES)} restricciones están activas")


def flatten_properties(props):
    """Convierte el dict de `properties` (puede tener sub-dicts/listas de dicts anidadas) a algo
    que Neo4j acepta como propiedades: solo primitivos o listas homogéneas de primitivos.

    Los campos simples se dejan tal cual. Los campos anidados (dict, lista de dicts, etc.) se
    serializan a JSON en un campo "<clave>_json" en vez de perderse. Los campos en CAMPOS_EXCLUIR
    (blobs pesados como los de moléculas en base64) se descartan directamente.
    """
    resultado = {}
    for clave, valor in props.items():
        if clave in CAMPOS_EXCLUIR or valor is None:
            continue
        if isinstance(valor, (str, int, float, bool)):
            resultado[clave] = valor
        elif isinstance(valor, list) and all(isinstance(v, (str, int, float, bool)) for v in valor):
            resultado[clave] = valor
        else:
            resultado[f"{clave}_json"] = json.dumps(valor, default=str)
    return resultado


def _con_reintentos(session, query, rows, max_reintentos=MAX_REINTENTOS):
    """Corre una consulta reintentando ante TransientError (interbloqueos/conflictos de lock),
    con espera exponencial entre intentos. Con un solo proceso escribiendo (sin concurrencia)
    esto debería disparar poco, pero Neo4j puede generar TransientError igual por su propio
    housekeeping interno (checkpoints, etc.) durante una carga larga.
    """
    for intento in range(max_reintentos):
        try:
            #.consume() fuerza a que la escritura se ejecute y confirme aca mismo, asi un
            #TransientError del servidor cae dentro de este try (session.run por si solo es
            #perezoso: el error podria no salir hasta consumir el resultado).
            return session.run(query, rows=rows).consume()
        except TransientError:
            if intento == max_reintentos - 1:
                raise
            time.sleep(2 ** intento)


def _lotes(path, batch_size):
    """Itera un parquet en lotes (pyarrow RecordBatch) sin cargarlo entero a memoria."""
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=batch_size):
        yield pa.Table.from_batches([batch]).to_pylist()


def cargar_nodos(driver, tipo):
    path = okg.get_file(f"nodes/{tipo}.parquet")
    label = label_de(tipo)
    total = pq.ParquetFile(path).metadata.num_rows
    cargados = 0
    with driver.session() as session:
        for filas_crudas in _lotes(path, BATCH_SIZE):
            filas = [
                {"id": f["id"], "props": flatten_properties(f["properties"])}
                for f in filas_crudas
            ]
            _con_reintentos(
                session,
                f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row.props",
                filas,
            )
            cargados += len(filas)
            log(f"  {tipo} ({label}): {cargados}/{total}")
    log(f"  {tipo} ({label}): {cargados}/{total} - listo")


def cargar_relaciones(driver, tipo_relacion):
    path = okg.get_file(f"edges/{tipo_relacion}.parquet")
    total = pq.ParquetFile(path).metadata.num_rows
    tipo_origen, tipo_destino = EDGE_TYPE_NODE_TYPES[tipo_relacion]
    label_origen, label_destino = label_de(tipo_origen), label_de(tipo_destino)
    cargados = 0
    with driver.session() as session:
        for filas_crudas in _lotes(path, BATCH_SIZE):
            #el tipo de relacion de Neo4j no se puede parametrizar en Cypher, asi que agrupamos
            #cada lote por el valor real de `relation` (puede haber mas de uno por archivo, ej.
            #drug_disease tiene INDICATION / CONTRAINDICATION / OFF_LABEL_USE) y armamos una
            #consulta por grupo.
            por_relacion = {}
            for f in filas_crudas:
                tipo_rel = f["relation"].upper().replace(" ", "_").replace("-", "_")
                props = flatten_properties(f["properties"])
                props["undirected"] = f["undirected"]
                por_relacion.setdefault(tipo_rel, []).append(
                    {"from": f["from"], "to": f["to"], "props": props}
                )
            for tipo_rel, filas in por_relacion.items():
                #las dos etiquetas (label_origen/label_destino) son las que hacen que este MATCH
                #use el indice de la restriccion de unicidad en vez de recorrer todos los nodos
                #del grafo buscando el `id`: sin etiqueta, la restriccion (que es por etiqueta)
                #no se puede aprovechar.
                _con_reintentos(
                    session,
                    f"UNWIND $rows AS row "
                    f"MATCH (a:{label_origen} {{id: row.from}}) MATCH (b:{label_destino} {{id: row.to}}) "
                    #las backticks alrededor del tipo de relacion son defensa extra: ya lo
                    #sanitizamos arriba (mayusculas, sin espacios/guiones), pero asi el Cypher
                    #queda valido igual si en algun momento aparece un caracter que no previmos.
                    f"MERGE (a)-[r:`{tipo_rel}`]->(b) SET r += row.props",
                    filas,
                )
            cargados += len(filas_crudas)
            log(f"  {tipo_relacion}: {cargados}/{total}")
    log(f"  {tipo_relacion}: {cargados}/{total} - listo")


def main():
    driver = connect()
    try:
        crear_restricciones(driver)

        log(f"Cargando {len(NODE_TYPES)} tipos de nodo...")
        for tipo in NODE_TYPES:
            cargar_nodos(driver, tipo)

        log(f"Cargando {len(EDGE_TYPES)} tipos de relación...")
        for tipo_relacion in EDGE_TYPES:
            try:
                cargar_relaciones(driver, tipo_relacion)
            except Neo4jError as e:
                log(f"  {tipo_relacion}: ERROR ({e}) - seguimos con el resto")

        log("Carga terminada.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
