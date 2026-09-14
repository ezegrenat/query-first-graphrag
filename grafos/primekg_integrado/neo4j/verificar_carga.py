"""Compara lo que hay en neo4j-thesis contra los CSV de origen, conteo por conteo.

Uso: python verificar_carga.py

Falla con AssertionError en el primer conteo que no coincida. Lo que se compara:
- nodos por label contra nodos por tipo en el CSV,
- aristas por tipo de relacion contra las del CSV colapsadas a una por par (y la estrella BERT
  aparte),
- que ningun nodo tenga dos labels ni una relacion se haya cargado en los dos sentidos.
"""
from neo4j import GraphDatabase

from cargar_grafo import leer_aristas, leer_nodos
from config import LABEL_POR_TIPO, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


def main():
    nodos = leer_nodos()
    aristas = leer_aristas()
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        print("nodos:")
        for tipo, label in LABEL_POR_TIPO.items():
            en_csv = int((nodos.node_type == tipo).sum())
            en_neo4j = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
            print(f"  {label:8} csv {en_csv:7}  neo4j {en_neo4j:7}")
            assert en_csv == en_neo4j, f"{label}: {en_csv} en el CSV y {en_neo4j} en Neo4j"

        grupos_csv = int(nodos.es_grupo_bert.sum())
        grupos_neo4j = session.run("MATCH (n:Disease {es_grupo_bert: true}) RETURN count(n) AS c").single()["c"]
        print(f"  grupos BERT: csv {grupos_csv}  neo4j {grupos_neo4j}")
        assert grupos_csv == grupos_neo4j

        print("aristas:")
        for relacion, cuantas in aristas.relacion.value_counts().items():
            en_neo4j = session.run(f"MATCH ()-[r:{relacion}]->() RETURN count(r) AS c").single()["c"]
            print(f"  {relacion:16} csv {int(cuantas):7}  neo4j {en_neo4j:7}")
            assert int(cuantas) == en_neo4j, f"{relacion}: {cuantas} en el CSV y {en_neo4j} en Neo4j"

        dobles = session.run(
            "MATCH (a)-[r]->(b) WHERE (b)-[]->(a) RETURN count(r) AS c").single()["c"]
        print(f"  pares con relacion en los dos sentidos: {dobles}")
        assert dobles == 0, "hay aristas cargadas en los dos sentidos"

        multi_label = session.run(
            "MATCH (n) WHERE size(labels(n)) > 1 RETURN count(n) AS c").single()["c"]
        assert multi_label == 0, f"{multi_label} nodos con mas de un label"
        total = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        assert total == len(nodos), f"{total} nodos en Neo4j, {len(nodos)} en el CSV"
    driver.close()
    print("verificacion ok")


if __name__ == "__main__":
    main()
