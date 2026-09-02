"""Marca en la capa `Disease` de Neo4j qué nodos son enfermedades y cuáles no. Es preferible hacer esto antes que directamente borrar los nodos que no son enfermedades. 
Se toma el criterio de que un nodo es enfermedad si no tiene como ancestro a ninguna de las tres raíces de la ontología que no son enfermedades y además tiene nombre no nulo ni vacío.
Eso se puede ver en limpieza_capa_disease.ipynb.

"""
import argparse
import os
import sys

from neo4j import GraphDatabase

#las credenciales viven en loader/, que es el otro lugar del proyecto que habla con Neo4j, y no
#se versionan. La ruta se arma desde este archivo para que el script corra desde cualquier
#directorio de trabajo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "loader"))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

PROPIEDAD = "is_truly_disease"
INDICE = "disease_is_truly"

#las tres raices de la ontologia que no son enfermedad. Tienen identificador EFO porque esa
#ontologia arma la jerarquia general, pero de ellas cuelgan tambien los nodos MONDO, OBA y
#Orphanet, asi que el criterio clasifica a toda la capa y no solo a los nodos de prefijo EFO
RAICES_NO_ENFERMEDAD = {
    "EFO_0001444": "medición o rasgo",
    "EFO_0000651": "fenotipo",
    "EFO_0002571": "procedimiento",
}

#el linaje incluye al propio nodo para que las raices queden descartadas junto con su descendencia
CYPHER_MARCAR = f"""
MATCH (d:Disease)
WITH d, coalesce(d.ancestors, []) + [d.id] AS linaje
SET d.{PROPIEDAD} = (
      NOT $medicion IN linaje
  AND NOT $fenotipo IN linaje
  AND NOT $procedimiento IN linaje
  AND d.name IS NOT NULL AND trim(d.name) <> ''
)
RETURN d.{PROPIEDAD} AS valor, count(*) AS n
"""

PARAMETROS = {"medicion": "EFO_0001444", "fenotipo": "EFO_0000651", "procedimiento": "EFO_0002571"}


def es_enfermedad(identificador, ancestros, nombre):
    linaje = set(ancestros or []) | {identificador}
    if linaje & set(RAICES_NO_ENFERMEDAD):
        return False
    return bool(nombre and nombre.strip())


def marcar(sesion):
    """Escribe la propiedad en la totalidad de los  nodos y devuelve {True: n, False: n}."""
    conteos = {fila["valor"]: fila["n"] for fila in sesion.run(CYPHER_MARCAR, **PARAMETROS)}
    sesion.run(f"CREATE INDEX {INDICE} IF NOT EXISTS FOR (d:Disease) ON (d.{PROPIEDAD})")
    return {True: conteos.get(True, 0), False: conteos.get(False, 0)}


def revertir(sesion):
    """Deja la capa como estaba: borra la propiedad de todos los nodos y el indice."""
    borrados = sesion.run(
        f"MATCH (d:Disease) WHERE d.{PROPIEDAD} IS NOT NULL "
        f"REMOVE d.{PROPIEDAD} RETURN count(*) AS n").single()["n"]
    sesion.run(f"DROP INDEX {INDICE} IF EXISTS")
    return borrados


def verificar(sesion):
    """Estado actual de la marca, sin escribir nada."""
    filas = sesion.run(
        f"MATCH (d:Disease) RETURN d.{PROPIEDAD} AS valor, count(*) AS n ORDER BY n DESC")
    return {fila["valor"]: fila["n"] for fila in filas}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verificar", action="store_true", help="solo informa, no escribe")
    parser.add_argument("--revertir", action="store_true", help="borra la propiedad y el índice")
    argumentos = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    with driver.session() as sesion:
        if argumentos.revertir:
            print(f"propiedad {PROPIEDAD} borrada de {revertir(sesion)} nodos")
        elif argumentos.verificar:
            for valor, cantidad in verificar(sesion).items():
                etiqueta = "sin marcar" if valor is None else f"{PROPIEDAD} = {valor}"
                print(f"  {cantidad:6d}  {etiqueta}")
        else:
            conteos = marcar(sesion)
            print(f"  {conteos[True]:6d}  {PROPIEDAD} = true")
            print(f"  {conteos[False]:6d}  {PROPIEDAD} = false")
            print(f"índice {INDICE} creado")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
