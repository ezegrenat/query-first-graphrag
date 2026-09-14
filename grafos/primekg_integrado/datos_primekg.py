"""Lectura de PrimeKG nativo desde los CSV originales, en datos/external/.

Este es el unico modulo de la carpeta que lee los archivos. Todo lo que se mide sobre PrimeKG
pasa por aca, para que si cambia la version del grafo o su formato el cambio sea en un solo lugar.

Los archivos son los originales de PrimeKG (Chandak, Huang y Zitnik 2023), sin ninguna limpieza:
    external/primekg_nodes.csv   una fila por nodo: node_index, node_id, node_type, node_name, node_source
    external/primekg_edges.csv   una fila por arista Y POR SENTIDO: relation, display_relation, x_index, y_index

Ese "y por sentido" importa: PrimeKG guarda cada arista dos veces, (x, y) y (y, x). Para contar
aristas de verdad hay que quedarse con una sola de las dos filas, y eso lo hacen las funciones de
abajo, que ademas verifican que la mitad descartada sea exactamente la mitad.

Las capas y planos del experimento usan solo tres tipos de nodo: genes, enfermedades y fenotipos.
Las drogas entran en un unico lugar, pares_indicacion(), que lista las drogas que PrimeKG une
directo a una enfermedad por "indication". Ese listado es el insumo para comparar la capa de drogas
de PrimeKG con la del grafo de Gonzalo (reunion del 2026-09-11); no es una capa del experimento.
"""
import os

import networkx as nx
import pandas as pd

_AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA_DATOS = os.path.join(_AQUI, "datos", "external")
ARCHIVO_NODOS = os.path.join(CARPETA_DATOS, "primekg_nodes.csv")
ARCHIVO_ARISTAS = os.path.join(CARPETA_DATOS, "primekg_edges.csv")

#los tres tipos de nodo del alcance, con el nombre exacto que usa la columna node_type del CSV
TIPOS = ("gene/protein", "disease", "effect/phenotype")

#las capas bipartitas entre esos tres tipos, escritas una por una. Cada entrada es
#(tipo A, tipo B, nombre de la relacion en la columna "relation" del CSV).
#Se deja afuera disease_phenotype_negative (1.193 filas, "phenotype absent"): es la ausencia de un
#fenotipo en una enfermedad, no una conexion, y para ir a buscar vecinos de la capa B no sirve.
CAPAS = {
    "disease_gene": ("disease", "gene/protein", "disease_protein"),
    "disease_phenotype": ("disease", "effect/phenotype", "disease_phenotype_positive"),
    "gene_phenotype": ("gene/protein", "effect/phenotype", "phenotype_protein"),
}

#los planos homogeneos: un tipo de nodo y la unica relacion intracapa que tiene en PrimeKG.
#gene es el interactoma (ppi); disease y phenotype son la jerarquia padre-hijo de sus ontologias
#(MONDO y HPO), que es lo mismo que era PARENT en OptimusKG.
PLANOS = {
    "gene": ("gene/protein", "protein_protein"),
    "disease": ("disease", "disease_disease"),
    "phenotype": ("effect/phenotype", "phenotype_phenotype"),
}

_cache = {}


def _nodos_completos():
    if "nodos" not in _cache:
        _cache["nodos"] = pd.read_csv(ARCHIVO_NODOS)
    return _cache["nodos"]


def _aristas_completas():
    #el CSV pesa 386 MB y tarda unos segundos en leerse; se lee una sola vez por proceso
    if "aristas" not in _cache:
        _cache["aristas"] = pd.read_csv(ARCHIVO_ARISTAS)
    return _cache["aristas"]


def cargar_nodos():
    """DataFrame con los nodos de los tres tipos del alcance, indexado por node_index."""
    nodos = _nodos_completos()
    nodos = nodos[nodos.node_type.isin(TIPOS)]
    return nodos.set_index("node_index")


def cargar_aristas():
    """DataFrame con las filas del CSV de aristas cuyos dos extremos son de los tres tipos del
    alcance, con dos columnas mas, x_type e y_type, con el tipo de cada extremo. Sigue teniendo
    cada arista en los dos sentidos: es la vista cruda, para contar filas contra el CSV."""
    tipo_por_indice = _nodos_completos().set_index("node_index").node_type
    aristas = _aristas_completas().copy()
    aristas["x_type"] = aristas.x_index.map(tipo_por_indice)
    aristas["y_type"] = aristas.y_index.map(tipo_por_indice)
    return aristas[aristas.x_type.isin(TIPOS) & aristas.y_type.isin(TIPOS)]


def _una_fila_por_arista(filas):
    """Se queda con la fila (x, y) de cada par y descarta la (y, x). Verifica que el CSV de verdad
    traiga las dos, porque si no el conteo quedaria a la mitad sin que nadie lo note."""
    pares = set(zip(filas.x_index, filas.y_index))
    con_inversa = sum((b, a) in pares for a, b in pares)
    if con_inversa != len(pares):
        raise ValueError(f"hay {len(pares) - con_inversa} filas sin su inversa; "
                         "el CSV no tiene la forma esperada")
    return filas[filas.x_index < filas.y_index]


def capa_bipartita(nombre):
    """DataFrame de pares (a, b) de la capa CAPAS[nombre], una fila por par, con a del tipo A y b
    del tipo B. Es "tal cual": sin umbral de evidencia ni filtro sobre los nodos."""
    tipo_a, tipo_b, relacion = CAPAS[nombre]
    aristas = cargar_aristas()
    filas = aristas[(aristas.relation == relacion)
                    & (aristas.x_type == tipo_a) & (aristas.y_type == tipo_b)]
    #en una capa bipartita los dos extremos son de tipos distintos, asi que quedarse con las filas
    #que van de A a B ya deja una fila por par; se verifica que el sentido inverso exista igual
    inversas = aristas[(aristas.relation == relacion)
                       & (aristas.x_type == tipo_b) & (aristas.y_type == tipo_a)]
    if len(inversas) != len(filas):
        raise ValueError(f"la capa {nombre} tiene {len(filas)} filas de A a B y "
                         f"{len(inversas)} de B a A; el CSV no tiene la forma esperada")
    return pd.DataFrame({"a": filas.x_index.values, "b": filas.y_index.values})


def plano(nombre):
    """networkx.Graph del plano homogeneo PLANOS[nombre]: solo los nodos que tienen al menos una
    arista, cada arista una vez, sin autobucles. Es la red donde correria DIAMOnD."""
    tipo, relacion = PLANOS[nombre]
    aristas = cargar_aristas()
    filas = aristas[(aristas.relation == relacion)
                    & (aristas.x_type == tipo) & (aristas.y_type == tipo)]
    filas = _una_fila_por_arista(filas)
    red = nx.Graph()
    red.add_edges_from(zip(filas.x_index, filas.y_index))
    red.remove_edges_from(nx.selfloop_edges(red))
    return red


def pares_indicacion():
    """DataFrame con los pares droga-enfermedad que PrimeKG une por la relacion "indication", una
    fila por par. Columnas: indice, id y nombre de la droga (el id es de DrugBank), indice, id,
    nombre y fuente de la enfermedad. La fuente es "MONDO" para una enfermedad de MONDO y
    "MONDO_grouped" para los agrupamientos de PrimeKG, cuyo id es la lista de ids de MONDO del
    grupo pegados con "_".

    A diferencia del resto del modulo, parte de los nodos completos, porque cargar_nodos() deja
    afuera a las drogas."""
    nodos = _nodos_completos().set_index("node_index")
    aristas = _aristas_completas()
    indicaciones = aristas[aristas.relation == "indication"]
    tipo_x = indicaciones.x_index.map(nodos.node_type)
    tipo_y = indicaciones.y_index.map(nodos.node_type)

    #la relacion es bipartita (droga, enfermedad), asi que quedarse con las filas que van de la
    #droga a la enfermedad deja una fila por par; se verifica que el sentido inverso exista igual
    de_droga = indicaciones[(tipo_x == "drug") & (tipo_y == "disease")]
    de_enfermedad = indicaciones[(tipo_x == "disease") & (tipo_y == "drug")]
    if len(de_droga) + len(de_enfermedad) != len(indicaciones):
        raise ValueError("hay filas de indication que no unen una droga con una enfermedad")
    if len(de_droga) != len(de_enfermedad):
        raise ValueError(f"indication tiene {len(de_droga)} filas de droga a enfermedad y "
                         f"{len(de_enfermedad)} de enfermedad a droga; el CSV no tiene la forma esperada")

    droga = nodos.loc[de_droga.x_index]
    enfermedad = nodos.loc[de_droga.y_index]
    return pd.DataFrame({
        "drug_index": de_droga.x_index.values,
        "drugbank_id": droga.node_id.values,
        "droga": droga.node_name.values,
        "disease_index": de_droga.y_index.values,
        "disease_node_id": enfermedad.node_id.values,
        "enfermedad": enfermedad.node_name.values,
        "disease_source": enfermedad.node_source.values,
    })
