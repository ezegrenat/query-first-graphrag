"""Escribe en cada nodo Disease de Neo4j la propiedad canonical_id: el identificador del nodo que lo representa cuando es un duplicado, o el suyo propio cuando no lo es. Los duplicados salen unicamente de equivalencias declaradas, nunca de heuristicas sobre nombres o vecindarios: los xrefs que MONDO trae en cada nodo y que ya estan cargados en la base, y el archivo de mapeos SSSOM que publica MONDO, fijado a un release y verificado por sha256. El script es autocontenido: lo unico que importa del resto del proyecto son las credenciales de Neo4j, asi que se lee entero de arriba abajo y se corre sin haber abierto el notebook redundancia_entre_nodos.ipynb, que es donde se justifica el criterio. No borra nodos ni mueve aristas. Se escribe en los 36.345 nodos de la capa a proposito, incluidos los que no tienen duplicado, para que un nodo sin la propiedad signifique que el marcado nunca se corrio."""
import argparse
import csv
import hashlib
import os
import sys
import urllib.request

import pandas as pd
from neo4j import GraphDatabase

#las credenciales viven en loader/, que es el otro lugar del proyecto que habla con Neo4j, y no
#se versionan. la ruta se arma desde este archivo para que el script corra desde cualquier
#directorio de trabajo
_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, "..", "loader"))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

PROPIEDAD = "canonical_id"
INDICE = "disease_canonical_id"
TAMANO_LOTE = 5000

#el archivo de mapeos de MONDO. la direccion canonica (purl.obolibrary.org) redirige a la rama
#master del repositorio y cambia sin aviso, por eso se fija al release y se verifica el sha256
MONDO_TAG = "v2026-09-01"
MONDO_SSSOM_URL = (f"https://raw.githubusercontent.com/monarch-initiative/mondo/{MONDO_TAG}"
                   "/src/ontology/mappings/mondo.sssom.tsv")
MONDO_SSSOM_SHA256 = "317ac4bf93be1deff4406b4d7d18bb730ead3c4f5c7c814f75d24be7f6ef302f"
RUTA_SSSOM = os.path.join(_AQUI, "datos", "mondo.sssom.tsv")


#Las cinco piezas que siguen resuelven el criterio en memoria, sin tocar Neo4j: de que declara
#cada fuente a que nodo representa a cada grupo. Estan escritas aca y no importadas de ningun
#lado para que este script se lea y se corra solo. El notebook que justifica el criterio tiene su
#propia copia en redundancia.py, y test_marcar_id_canonico.py verifica que las dos coincidan.


def normalizar_identificador(identificador):
    """Lleva un identificador a una forma comparable: MONDO:0007256 y MONDO_0007256 son el mismo nodo escrito con los dos separadores que conviven en el grafo."""
    if identificador is None or not isinstance(identificador, str):
        return ""
    return identificador.strip().replace(":", "_")


def pares_por_referencia(referencias_por_id, identificadores_existentes):
    """Empareja un nodo con otro cuando una de sus referencias cruzadas apunta a un identificador que existe como nodo de la misma capa. Los dos lados se normalizan porque el grafo mezcla los separadores : y _ en el mismo campo."""
    existentes = {normalizar_identificador(i): i for i in identificadores_existentes}
    pares = []
    for identificador, referencias in referencias_por_id.items():
        for referencia in referencias or []:
            apuntado = existentes.get(normalizar_identificador(referencia))
            if apuntado is None or apuntado == identificador:
                continue
            pares.append((min(identificador, apuntado), max(identificador, apuntado), referencia))
    return sorted(set(pares))


def pares_desde_sssom(mapeos, identificadores_existentes, predicado="skos:exactMatch"):
    """Saca de una tabla SSSOM los pares de identificadores que existen los dos como nodo de la capa, quedandose solo con el predicado pedido. Un mapeo hacia un vocabulario que no esta cargado no es un duplicado del grafo, por eso el filtro por existencia. Devuelve los pares ordenados y sin repetir."""
    existentes = {normalizar_identificador(i): i for i in identificadores_existentes}
    filas = mapeos[mapeos["predicate_id"] == predicado]
    pares = set()
    for sujeto, objeto in zip(filas["subject_id"], filas["object_id"]):
        a = existentes.get(normalizar_identificador(sujeto))
        b = existentes.get(normalizar_identificador(objeto))
        if a is None or b is None or a == b:
            continue
        pares.add((min(a, b), max(a, b)))
    return sorted(pares)


def grupos_de_equivalencia(pares):
    """Arma los grupos de nodos equivalentes como componentes conexas del grafo de pares: si A es igual a B y B es igual a C, los tres son un solo grupo. Cada grupo y la lista de grupos van ordenados para que el resultado no dependa del orden de entrada."""
    vecinos = {}
    for a, b in pares:
        vecinos.setdefault(a, set()).add(b)
        vecinos.setdefault(b, set()).add(a)
    vistos, grupos = set(), []
    for inicio in sorted(vecinos):
        if inicio in vistos:
            continue
        #recorrido en anchura sin recursion, la componente mas grande medida tiene 14 nodos pero
        #no hay razon para depender de eso
        grupo, pendientes = set(), [inicio]
        while pendientes:
            nodo = pendientes.pop()
            if nodo in grupo:
                continue
            grupo.add(nodo)
            pendientes.extend(vecinos[nodo] - grupo)
        vistos |= grupo
        grupos.append(sorted(grupo))
    return sorted(grupos)


#orden de preferencia entre ontologias cuando todo lo demas empata. MONDO va primero porque es la
#ontologia que armoniza a las otras, o sea la que existe para ser el identificador unico de una
#enfermedad. el resto de los espacios caen al final con el mismo valor
PRIORIDAD_DE_ONTOLOGIA = {"MONDO": 0, "Orphanet": 1, "EFO": 2, "DOID": 3, "NCIT": 4}


def elegir_representante(grupo, grado, jerarquia):
    """Elige el nodo que representa a un grupo de nodos redundantes, con una cascada de cuatro criterios: mas aristas, mas aristas de jerarquia, ontologia de mayor prioridad, y el identificador menor. Los tres primeros son sustantivos y el ultimo esta solo para que el resultado no dependa del orden en que llegue el grupo. Elegir representante no es lo mismo que descartar a los demas: quien llama decide si las aristas del resto se arrastran o se pierden."""
    def clave(identificador):
        espacio = str(identificador).split("_")[0].split(":")[0]
        return (-grado.get(identificador, 0),
                -jerarquia.get(identificador, 0),
                PRIORIDAD_DE_ONTOLOGIA.get(espacio, len(PRIORIDAD_DE_ONTOLOGIA)),
                str(identificador))
    return min(grupo, key=clave)


def obtener_sssom(ruta=RUTA_SSSOM):
    """Devuelve la tabla SSSOM de MONDO, bajandola si no esta, y corta si el archivo en disco no es el del release documentado."""
    if not os.path.exists(ruta):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        urllib.request.urlretrieve(MONDO_SSSOM_URL, ruta)
    with open(ruta, "rb") as archivo:
        sha = hashlib.sha256(archivo.read()).hexdigest()
    if sha != MONDO_SSSOM_SHA256:
        raise RuntimeError(f"{ruta} no es el archivo del release {MONDO_TAG}: sha256 {sha[:16]}")
    return pd.read_csv(ruta, sep="\t", comment="#", dtype=str)


def pares_declarados(sesion, sssom):
    """Los pares de enfermedades reales que alguna de las dos fuentes declara equivalentes. Solo entran nodos con is_truly_disease para que ningun nodo real quede absorbido por uno que la limpieza anterior descarto."""
    filas = list(sesion.run("MATCH (d:Disease) WHERE d.is_truly_disease RETURN d.id AS id, d.xrefs AS xrefs"))
    identificadores = [f["id"] for f in filas]
    xrefs = {f["id"]: f["xrefs"] for f in filas if f["xrefs"] is not None}
    #obsolete_xrefs no entra: son referencias que la propia ontologia marco como deprecadas
    desde_xrefs = {(a, b) for a, b, _ in pares_por_referencia(xrefs, identificadores)}
    desde_sssom = set(pares_desde_sssom(sssom, identificadores))
    return {"xrefs": desde_xrefs, "sssom": desde_sssom}


def construir_mapeo(pares, grado, jerarquia):
    """Del conjunto de pares al diccionario id a representante, agrupando por componentes conexas y eligiendo en cada grupo el nodo con mas aristas, con mas jerarquia, de la ontologia prioritaria, o de identificador menor, en ese orden. El representante se mapea a si mismo."""
    mapeo = {}
    for grupo in grupos_de_equivalencia(sorted(pares)):
        representante = elegir_representante(grupo, grado, jerarquia)
        for nodo in grupo:
            mapeo[nodo] = representante
    validar_mapeo(mapeo)
    return mapeo


def validar_mapeo(mapeo):
    """Corta si el mapeo tiene cadenas: un representante que apunte a otro dejaria nodos con canonical_id distinto de id y sin ser duplicados de nadie, y filtrar por canonical_id = id los perderia en silencio."""
    for identificador, representante in mapeo.items():
        if representante not in mapeo:
            raise ValueError(f"el representante {representante} de {identificador} no esta en el mapeo")
        if mapeo[representante] != representante:
            raise ValueError(f"el representante {representante} no se apunta a si mismo")


def calcular(sesion):
    """Recalcula el mapeo completo contra la base y devuelve el diccionario junto con los conteos que lo describen."""
    fuentes = pares_declarados(sesion, obtener_sssom())
    pares = fuentes["xrefs"] | fuentes["sssom"]
    involucrados = sorted({nodo for par in pares for nodo in par})
    perfil = list(sesion.run("""
        MATCH (d:Disease) WHERE d.id IN $ids
        RETURN d.id AS id, COUNT { (d)--() } AS grado, COUNT { (d)-[:PARENT]-() } AS jerarquia""",
        ids=involucrados))
    grado = {f["id"]: f["grado"] for f in perfil}
    jerarquia = {f["id"]: f["jerarquia"] for f in perfil}
    mapeo = construir_mapeo(pares, grado, jerarquia)
    conteos = {
        "pares por xrefs": len(fuentes["xrefs"]), "pares por sssom": len(fuentes["sssom"]),
        "pares en ambas": len(fuentes["xrefs"] & fuentes["sssom"]), "pares declarados": len(pares),
        "nodos involucrados": len(involucrados), "grupos": len(set(mapeo.values())),
        "absorbidos": sum(1 for i, r in mapeo.items() if i != r),
    }
    return mapeo, conteos


def marcar(sesion, mapeo):
    """Escribe la propiedad en toda la capa y devuelve cuantos nodos quedaron apuntando a otro. Primero todos a si mismos y despues los del mapeo, asi una corrida con menos duplicados que la anterior deja limpios los nodos que dejaron de serlo."""
    sesion.run(f"MATCH (d:Disease) SET d.{PROPIEDAD} = d.id")
    filas = [{"id": i, "representante": r} for i, r in mapeo.items() if i != r]
    escritos = 0
    for inicio in range(0, len(filas), TAMANO_LOTE):
        resultado = sesion.run(
            f"UNWIND $filas AS fila MATCH (d:Disease {{id: fila.id}}) "
            f"SET d.{PROPIEDAD} = fila.representante RETURN count(d) AS n",
            filas=filas[inicio:inicio + TAMANO_LOTE]).single()
        escritos += resultado["n"]
    if escritos != len(filas):
        raise RuntimeError(f"el mapeo tiene {len(filas)} nodos absorbidos y se escribieron {escritos}")
    sesion.run(f"CREATE INDEX {INDICE} IF NOT EXISTS FOR (d:Disease) ON (d.{PROPIEDAD})")
    return escritos


def revertir(sesion):
    """Deja la capa como estaba: borra la propiedad de todos los nodos y el indice."""
    borrados = sesion.run(
        f"MATCH (d:Disease) WHERE d.{PROPIEDAD} IS NOT NULL "
        f"REMOVE d.{PROPIEDAD} RETURN count(*) AS n").single()["n"]
    sesion.run(f"DROP INDEX {INDICE} IF EXISTS")
    return borrados


def verificar(sesion):
    """Estado actual de la marca, sin escribir nada: nodos sin la propiedad, canonicos y absorbidos."""
    fila = sesion.run(f"""
        MATCH (d:Disease)
        RETURN sum(CASE WHEN d.{PROPIEDAD} IS NULL THEN 1 ELSE 0 END) AS sin_marcar,
               sum(CASE WHEN d.{PROPIEDAD} = d.id THEN 1 ELSE 0 END) AS canonicos,
               sum(CASE WHEN d.{PROPIEDAD} IS NOT NULL AND d.{PROPIEDAD} <> d.id THEN 1 ELSE 0 END) AS absorbidos
        """).single()
    return {"sin marcar": fila["sin_marcar"], "canonicos": fila["canonicos"],
            "absorbidos": fila["absorbidos"]}


def exportar(mapeo, ruta):
    """Escribe el mapeo a un CSV, solo los nodos absorbidos, para revisarlo antes o despues de aplicarlo."""
    with open(ruta, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["id", PROPIEDAD])
        for identificador, representante in sorted(mapeo.items()):
            if identificador != representante:
                escritor.writerow([identificador, representante])


def main():
    parser = argparse.ArgumentParser(description=__doc__.split(".")[0])
    parser.add_argument("--simular", action="store_true",
                        help="calcula el mapeo y lo informa, sin escribir en la base")
    parser.add_argument("--verificar", action="store_true", help="solo informa el estado de la marca")
    parser.add_argument("--revertir", action="store_true", help="borra la propiedad y el índice")
    parser.add_argument("--exportar", metavar="CSV", help="escribe el mapeo calculado a este archivo")
    argumentos = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    with driver.session() as sesion:
        if argumentos.revertir:
            print(f"propiedad {PROPIEDAD} borrada de {revertir(sesion)} nodos")
        elif argumentos.verificar:
            for etiqueta, cantidad in verificar(sesion).items():
                print(f"  {cantidad:6d}  {etiqueta}")
        else:
            mapeo, conteos = calcular(sesion)
            for etiqueta, cantidad in conteos.items():
                print(f"  {cantidad:6d}  {etiqueta}")
            if argumentos.exportar:
                exportar(mapeo, argumentos.exportar)
                print(f"mapeo escrito en {argumentos.exportar}")
            if argumentos.simular:
                print("simulación: no se escribió nada en la base")
            else:
                absorbidos = marcar(sesion, mapeo)
                estado = verificar(sesion)
                print(f"\n  {estado['canonicos']:6d}  {PROPIEDAD} = id (canónicos)")
                print(f"  {absorbidos:6d}  {PROPIEDAD} apunta a otro nodo (absorbidos)")
                print(f"índice {INDICE} creado")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
