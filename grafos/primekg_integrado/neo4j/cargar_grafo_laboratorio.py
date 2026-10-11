"""Reemplaza la capa de drogas del contenedor neo4j-thesis por los compuestos del grafo de PrimeKG integrado con la red del laboratorio, y verifica la carga.

Uso, con el contenedor levantado (docker start neo4j-thesis) y PrimeKG integrado ya cargado por cargar_grafo.py:
    python grafos/primekg_integrado/neo4j/cargar_grafo_laboratorio.py

Lo de PrimeKG integrado (genes, enfermedades, pathways y sus aristas) no se toca: el grafo con los compuestos repite esos nodos con el mismo node_index. Solo se cargan los nodos drug y sus tres tipos de arista.

Que se carga:
- Antes que nada se borran los Drug que hubiera, con sus aristas: MATCH (d:Drug) DETACH DELETE d.
- Nodos Drug, MERGE por id (CID_ y el numero de compuesto del laboratorio), con name, node_index, source, drugbank_id (vacio si el compuesto no es una droga con indicacion), chembl_id y ccd (varios unidos con |), cluster_id, molweight y tiene_indicacion. Llevan es_grupo_bert y es_complejo_signor en false para que los filtros del experimento que miran esas propiedades no fallen por propiedad ausente.
- INDICATION (Drug a Disease), DRUG_TARGET (Drug a Gene, con origen: chembl, biolip o both) y DRUG_DRUG (Drug a Drug, con weight), cada una en un solo sentido, como el resto del grafo. El experimento lee con -[r]- sin flecha.
- Una restriccion de unicidad sobre Drug.id, y dos indices sobre Gene.id y Disease.id (la unicidad de PrimeKG integrado es por node_index): son la clave del MATCH del lado de PrimeKG integrado al cargar y aceleran las consultas de vecinos del experimento.

Al final compara Neo4j contra los CSV conteo por conteo y falla con AssertionError en el primero que no coincida: nodos y aristas de cada tipo, que ninguna arista tenga extremos de otro tipo, que ninguna relacion de drogas este en los dos sentidos, que ningun Drug tenga otro label, y que las drogas sin ninguna arista sean las mismas.

Es idempotente (MERGE) y se puede deshacer entera sin tocar lo de PrimeKG integrado:
    MATCH (d:Drug) DETACH DELETE d
"""
import pandas as pd

from cargar_grafo import con_reintentos, conectar, log, lotes
from config import ARCHIVO_LAB_ARISTAS, ARCHIVO_LAB_DETALLE, ARCHIVO_LAB_NODOS

#(tipo de relacion, edge_type del CSV, label del extremo a, label del extremo b, propiedades fijas)
RELACIONES = [
    ("INDICATION", "drug_disease", "Drug", "Disease", {"source": "primekg"}),
    ("DRUG_TARGET", "drug_gene", "Drug", "Gene", {"source": "laboratorio"}),
    ("DRUG_DRUG", "drug_drug", "Drug", "Drug", {"source": "laboratorio"}),
]
#las columnas de aristas.csv que pasan a ser propiedad de cada relacion
PROPIEDADES = {"INDICATION": [], "DRUG_TARGET": ["origen"], "DRUG_DRUG": ["weight"]}


def leer_grafo():
    """Los nodos drug con su detalle y un DataFrame por relacion (x_id, y_id y sus propiedades), con los ids como texto y weight como numero."""
    nodos = pd.read_csv(ARCHIVO_LAB_NODOS, dtype=str)
    nodos = nodos[nodos.node_type == "drug"]
    detalle = pd.read_csv(ARCHIVO_LAB_DETALLE, dtype=str)
    #el detalle trae una fila por nodo drug y se cruza por node_id, asi el orden de los dos archivos no importa
    nodos = nodos.merge(detalle, on="node_id", how="left", validate="one_to_one")
    if nodos.tiene_indicacion.isna().any():
        raise ValueError("hay nodos drug sin fila en drogas_detalle.csv")

    todas = pd.read_csv(ARCHIVO_LAB_ARISTAS, dtype=str)
    aristas = {}
    for tipo, edge_type, _, _, _ in RELACIONES:
        filas = todas[todas.edge_type == edge_type]
        aristas[tipo] = filas[["x_id", "y_id"] + PROPIEDADES[tipo]].reset_index(drop=True)
    aristas["DRUG_DRUG"]["weight"] = aristas["DRUG_DRUG"].weight.astype(float)
    return nodos, aristas


def borrar_drogas(driver):
    with driver.session() as session:
        borrados = session.run("MATCH (d:Drug) RETURN count(d) AS c").single()["c"]
        #en lotes, para no armar una sola transaccion con todas las aristas de las drogas
        session.run("MATCH (d:Drug) CALL { WITH d DETACH DELETE d } IN TRANSACTIONS OF 5000 ROWS")
    log(f"  borrados {borrados} nodos Drug con sus aristas")


def cargar_drogas(driver, nodos):
    def valor(dato):
        return None if pd.isna(dato) else dato
    registros = [{"id": f.node_id, "name": f.node_name, "node_index": int(f.node_index), "drugbank_id": valor(f.drugbank_id),
                  "chembl_id": valor(f.chembl_id), "ccd": valor(f.ccd),
                  "cluster_id": None if pd.isna(f.cluster_id) else int(f.cluster_id),
                  "molweight": None if pd.isna(f.molweight) else float(f.molweight),
                  "tiene_indicacion": f.tiene_indicacion == "True"}
                 for f in nodos.itertuples()]
    with driver.session() as session:
        session.run("CREATE CONSTRAINT restriccion_drug IF NOT EXISTS FOR (n:Drug) REQUIRE n.id IS UNIQUE")
        session.run("CREATE INDEX indice_gene_id IF NOT EXISTS FOR (n:Gene) ON (n.id)")
        session.run("CREATE INDEX indice_disease_id IF NOT EXISTS FOR (n:Disease) ON (n.id)")
        for lote in lotes(registros):
            con_reintentos(session, "UNWIND $rows AS row MERGE (d:Drug {id: row.id}) "
                           "SET d.name = row.name, d.node_index = row.node_index, d.source = 'laboratorio', "
                           "d.drugbank_id = row.drugbank_id, d.chembl_id = row.chembl_id, d.ccd = row.ccd, "
                           "d.cluster_id = row.cluster_id, d.molweight = row.molweight, d.tiene_indicacion = row.tiene_indicacion, "
                           "d.es_grupo_bert = false, d.es_complejo_signor = false", lote)
    log(f"  Drug: {len(registros)} nodos")


def cargar_relacion(driver, tipo, label_a, label_b, aristas, fijas):
    """Una relacion tipo de label_a a label_b por fila de aristas, MERGE por par, con las columnas que no son los extremos como propiedades mas las fijas (source)."""
    propiedades = {**fijas, **{c: None for c in aristas.columns if c not in ("x_id", "y_id")}}
    registros = [{"a": f.x_id, "b": f.y_id, **{p: fijas.get(p, getattr(f, p, None)) for p in propiedades}}
                 for f in aristas.itertuples()]
    consulta = (f"UNWIND $rows AS row MATCH (a:{label_a} {{id: row.a}}) MATCH (b:{label_b} {{id: row.b}}) "
                f"MERGE (a)-[r:{tipo}]->(b) SET " + ", ".join(f"r.{p} = row.{p}" for p in propiedades))
    with driver.session() as session:
        for lote in lotes(registros):
            con_reintentos(session, consulta, lote)
    log(f"  {tipo} ({label_a} a {label_b}): {len(registros)} aristas")


def verificar(driver, nodos, aristas):
    def contar(consulta):
        return session.run(consulta).single()["c"]
    with driver.session() as session:
        assert contar("MATCH (d:Drug) RETURN count(d) AS c") == len(nodos), "Drug: Neo4j y CSV no coinciden"
        assert contar("MATCH (d:Drug) WHERE size(labels(d)) > 1 RETURN count(d) AS c") == 0, "Drug con mas de un label"
        assert "restriccion_drug" in {r["name"] for r in session.run("SHOW CONSTRAINTS").data()}, "falta la restriccion sobre Drug.id"
        for tipo, _, label_a, label_b, _ in RELACIONES:
            entre_tipos = contar(f"MATCH (:{label_a})-[r:{tipo}]->(:{label_b}) RETURN count(r) AS c")
            assert entre_tipos == len(aristas[tipo]), f"{tipo}: {entre_tipos} en Neo4j y {len(aristas[tipo])} en el CSV"
            assert contar(f"MATCH ()-[r:{tipo}]->() RETURN count(r) AS c") == entre_tipos, f"{tipo} con extremos de otro tipo"
        assert contar("MATCH (a:Drug)-[r]->(b) WHERE (b)-[]->(a) RETURN count(r) AS c") == 0, "relaciones de drogas en los dos sentidos"
        con_arista = set()
        for tipo in aristas:
            con_arista |= set(aristas[tipo].x_id) | set(aristas[tipo].y_id)
        sin_nada = contar("MATCH (d:Drug) WHERE NOT (d)--() RETURN count(d) AS c")
        assert sin_nada == len(set(nodos.node_id) - con_arista), "drogas sin aristas: Neo4j y CSV no coinciden"
    log("verificacion ok: Neo4j coincide con los CSV del grafo")


def main():
    nodos, aristas = leer_grafo()
    driver = conectar()
    try:
        borrar_drogas(driver)
        cargar_drogas(driver, nodos)
        for tipo, _, label_a, label_b, fijas in RELACIONES:
            cargar_relacion(driver, tipo, label_a, label_b, aristas[tipo], fijas)
        verificar(driver, nodos, aristas)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
