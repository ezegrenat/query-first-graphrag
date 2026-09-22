"""Selecciona el subgrafo de una query proyectando cada entidad con DIAMOnD. Recomendable leer especificacion.md, que documenta parametros, retornos, errores y casos borde."""
import os
import sys
import time
import warnings
from dataclasses import dataclass

import pandas as pd

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, "..", "manipulacion_grafo"))
sys.path.insert(0, os.path.join(_AQUI, "..", "expansion"))

from diamond_algoritmo import DIAMOnD  # noqa: E402
from planos_y_pasos import (CELDAS, MIN_SEMILLAS, PLANOS, UMBRAL_DRUG_MINIMO, conectar,  # noqa: E402
                            obtener_plano, plano_drug)

#cache propio de este modulo, separado del de cada corrida de la calibracion
CACHE_PLANOS = os.path.join(_AQUI, "cache_planos")

SEMILLA_DE_HASH = "42"

ROL_ENTIDAD = "entidad"
ROL_SEMILLA = "semilla"
ROL_VECINO_FUERA_DEL_PLANO = "vecino_fuera_del_plano"
ROL_AGREGADO = "agregado"

LABELS = frozenset(plano.tipo for plano in PLANOS.values())

COLUMNAS_NODOS = ["label", "id", "nombre", "procedencias"]
COLUMNAS_ARISTAS = ["label_a", "id_a", "label_b", "id_b", "tipo", "propiedades"]


@dataclass
class Grafo:
    """La conexion a Neo4j y los tres planos ya cargados."""

    gds: object
    planos: dict[str, object]
    umbral_drug: float


@dataclass(frozen=True)
class Procedencia:
    """Por que un nodo esta en la seleccion: que entidad y que paso lo trajeron, con que rol."""

    entidad: tuple[str, str]
    paso: str | None
    rol: str
    iteracion: int | None = None
    p_valor: float | None = None


@dataclass
class Proyeccion:
    """Lo que produce un paso para una entidad."""

    entidad: tuple[str, str]
    paso: str | None
    nodos: dict[tuple[str, str], list[Procedencia]]
    expandio: bool


#los nodos de la query con todas sus procedencias, todavia sin aristas
Seleccion = dict[tuple[str, str], list[Procedencia]]


@dataclass
class Subgrafo:
    """Los nodos de la seleccion y las aristas que inducen en el grafo original. Todo construido solo para el return final"""

    nodos: pd.DataFrame
    aristas: pd.DataFrame


def cargar_grafo(umbral_drug=UMBRAL_DRUG_MINIMO, verbose=True):
    """Abre la conexion a Neo4j y carga los tres planos una sola vez."""

    plano_de_drogas = plano_drug(umbral_drug)
    if os.environ.get("PYTHONHASHSEED") != SEMILLA_DE_HASH:
        warnings.warn(f"PYTHONHASHSEED no vale {SEMILLA_DE_HASH}: los nodos que agregue DIAMOnD pueden "
                      "cambiar de una corrida a otra y no van a coincidir con los de la calibracion")
    gds = conectar()
    planos = {"gene": obtener_plano(gds, PLANOS["gene"], verbose, CACHE_PLANOS),
              "disease": obtener_plano(gds, PLANOS["disease"], verbose, CACHE_PLANOS),
              "drug": obtener_plano(gds, plano_de_drogas, verbose, CACHE_PLANOS)}
    return Grafo(gds, planos, umbral_drug)


def validar_entidad(G, entidad):
    """Levanta ValueError si la entidad no es un nodo del grafo con ese label."""
    label, id_entidad = entidad
    #el label se interpola en el Cypher mas abajo, asi que tiene que ser uno de los tres del alcance
    if label not in LABELS:
        raise ValueError(f"la entidad {entidad} no es de ninguno de los labels {sorted(LABELS)}")
    filas = G.gds.run_cypher(f"MATCH (n:{label} {{id: $id}}) RETURN count(n) AS cuantos",
                             params={"id": id_entidad})
    if not int(filas["cuantos"][0]):
        raise ValueError(f"la entidad {entidad} no esta en el grafo")


def cosechar_vecinos_de_entidad(G, entidad, celda):
    """Los ids de los vecinos de la entidad del tipo del plano, sin repetidos y ordenados."""	
    filas = G.gds.run_cypher(
        f"MATCH (a:{celda.origen} {{id: $id}})-[:{celda.relacion_cosecha}]-(b:{celda.tipo_destino}) "
        "RETURN DISTINCT b.id AS id", params={"id": entidad[1]})
    #no se filtran los grupos BERT
    return sorted(filas["id"])


def proyectar(G, entidad, paso, n_iter, min_semillas=MIN_SEMILLAS):
    """Corre un paso para una entidad: cosecha sus vecinos y expande con DIAMOnD en el plano."""
    if paso not in CELDAS:
        raise ValueError(f"el paso {paso!r} no es ninguno de {list(CELDAS)}")
    celda = CELDAS[paso]
    if celda.origen != entidad[0]:
        raise ValueError(f"el paso {paso} sale de {celda.origen} y la entidad {entidad} es de "
                         f"{entidad[0]}")
    validar_entidad(G, entidad)

    red = G.planos[celda.plano]
    label_destino = celda.tipo_destino
    nodos = {}
    semillas = []
    
    #cosechar los vecinos de tipo B de la entidad con la relacion del paso
    for id_vecino in cosechar_vecinos_de_entidad(G, entidad, celda):
        en_el_plano = id_vecino in red
        if en_el_plano:
            semillas.append(id_vecino)
        nodos[(label_destino, id_vecino)] = [Procedencia(
            entidad, paso, ROL_SEMILLA if en_el_plano else ROL_VECINO_FUERA_DEL_PLANO)]

    #con pocas semillas o sin iteraciones el paso igual aporta la cosecha, que ya esta en nodos
    expandio = len(semillas) >= min_semillas and n_iter > 0
    if expandio:

        for iteracion, (nodo, _k, _kb, p) in enumerate(DIAMOnD(red, semillas, n_iter),
                                                       start=1):
            nodos[(label_destino, nodo)] = [Procedencia(entidad, paso, ROL_AGREGADO, iteracion,
                                                        float(p))]
    return Proyeccion(entidad, paso, nodos, expandio)


def proyectar_heterogeneo(G, entidad, iter_por_paso, min_semillas=MIN_SEMILLAS):
    """Todas las proyecciones de una entidad: la trivial y una por cada paso con vecinos."""
    validar_entidad(G, entidad)
    for paso in iter_por_paso:
        if paso not in CELDAS:
            raise ValueError(f"el paso {paso!r} no es ninguno de {list(CELDAS)}")

    #la trivial deja a la entidad en el resultado aunque no tenga un solo vecino
    proyecciones = [Proyeccion(entidad, None, {entidad: [Procedencia(entidad, None, ROL_ENTIDAD)]},
                               False)]
    for paso, celda in CELDAS.items():
        #los pasos de iter_por_paso que salen de otro tipo son de otra entidad de la query
        if celda.origen != entidad[0]:
            continue
        proyeccion = proyectar(G, entidad, paso, iter_por_paso.get(paso, 0), min_semillas)
        if proyeccion.nodos:
            proyecciones.append(proyeccion)
    return proyecciones


def unir(proyecciones):
    """Junta las proyecciones en una seleccion, conservando todas las procedencias de cada nodo."""
    seleccion = {}
    for proyeccion in proyecciones:
        for nodo, procedencias in proyeccion.nodos.items():
            seleccion.setdefault(nodo, []).extend(procedencias)
    return seleccion


def refinar(G, seleccion):
    """Lugar reservado para el random walk multicapa, que hoy devuelve la seleccion sin cambios."""
    return seleccion


def materializar_subgrafo(G, seleccion):
    """Los nodos de la seleccion y todas las aristas del grafo original entre ellos."""
    if not seleccion:
        return Subgrafo(pd.DataFrame(columns=COLUMNAS_NODOS), pd.DataFrame(columns=COLUMNAS_ARISTAS))

    ids_por_label = {label: [] for label in sorted(LABELS)}
    for label, id_nodo in seleccion:
        if label not in ids_por_label:
            raise ValueError(f"el nodo {(label, id_nodo)} no es de ninguno de los labels "
                             f"{sorted(LABELS)}, asi que no puede estar en Neo4j")
        ids_por_label[label].append(id_nodo)
    parametros = {f"ids_{label.lower()}": ids for label, ids in ids_por_label.items()}

    ramas = " UNION ".join(f"MATCH (a:{label}) WHERE a.id IN $ids_{label.lower()} "
                           f"RETURN a, '{label}' AS label" for label in ids_por_label)

    filas_nodos = G.gds.run_cypher(
        f"CALL {{ {ramas} }} "
        "RETURN label, a.id AS id, a.name AS nombre, elementId(a) AS interno", params=parametros)
    faltantes = set(seleccion) - set(zip(filas_nodos["label"], filas_nodos["id"]))
    if faltantes:
        raise ValueError(f"{len(faltantes)} nodos de la seleccion no estan en Neo4j, "
                         f"por ejemplo {sorted(faltantes)[:3]}")

    filas_aristas = G.gds.run_cypher(
        f"CALL {{ {ramas} }} "
        "WITH collect(a) AS sel "
        "UNWIND sel AS a "
        "MATCH (a)-[r]-(b) "
        #cada arista se ve desde sus dos extremos, y el orden de los elementId deja una sola copia
        "WHERE b IN sel AND elementId(a) < elementId(b) "
        "RETURN elementId(a) AS interno_a, elementId(b) AS interno_b, type(r) AS tipo, "
        "properties(r) AS propiedades",
        params=parametros)

    #el par (label, id) no se puede recuperar del nodo de Neo4j sin ambiguedad si tuviera dos
    #labels, asi que se vuelve por el elementId con el que se lo trajo
    por_interno = dict(zip(filas_nodos["interno"], zip(filas_nodos["label"], filas_nodos["id"])))
    nodos = pd.DataFrame({
        "label": filas_nodos["label"],
        "id": filas_nodos["id"],
        "nombre": filas_nodos["nombre"],
        "procedencias": [seleccion[clave]
                         for clave in zip(filas_nodos["label"], filas_nodos["id"])]},
        columns=COLUMNAS_NODOS)
    aristas = pd.DataFrame({
        "label_a": [por_interno[i][0] for i in filas_aristas["interno_a"]],
        "id_a": [por_interno[i][1] for i in filas_aristas["interno_a"]],
        "label_b": [por_interno[i][0] for i in filas_aristas["interno_b"]],
        "id_b": [por_interno[i][1] for i in filas_aristas["interno_b"]],
        "tipo": filas_aristas["tipo"],
        "propiedades": filas_aristas["propiedades"]}, columns=COLUMNAS_ARISTAS)
    return Subgrafo(nodos, aristas)


def obtener_subgrafo_query(G, entidades, iter_por_paso, min_semillas=MIN_SEMILLAS):
    """todo el proceso para el subgrafo  de una query: proyecta cada entidad, une, refina y materializa el subgrafo"""
    proyecciones = [proyeccion for entidad in dict.fromkeys(entidades)
                    for proyeccion in proyectar_heterogeneo(G, entidad, iter_por_paso, min_semillas)]
    return materializar_subgrafo(G, refinar(G, unir(proyecciones)))


if __name__ == "__main__":
    #completar con las entidades de la query como pares (label, id), por ejemplo
    #("Disease", "C0007570") para Celiac Disease. El label es uno de Gene, Disease o Drug y el id
    #es el del nodo en Neo4j
    ENTIDADES = []
    #iteraciones de DIAMOnD por paso, por ejemplo {"disease_a_gene": 100, "disease_a_drug": 20}.
    #Los pasos que no figuran solo cosechan vecinos, sin expandir
    ITER_POR_PASO = {}

    if not ENTIDADES:
        sys.exit("completar ENTIDADES e ITER_POR_PASO en el main de subgrafo_query.py")

    reloj = time.time()
    grafo = cargar_grafo()
    subgrafo = obtener_subgrafo_query(grafo, ENTIDADES, ITER_POR_PASO)
    print(f"subgrafo: {len(subgrafo.nodos)} nodos y {len(subgrafo.aristas)} aristas "
          f"en {time.time() - reloj:.1f}s")
    print("\nnodos por label:")
    print(subgrafo.nodos["label"].value_counts().to_string())
    print("\naristas por tipo:")
    print(subgrafo.aristas["tipo"].value_counts().to_string())
