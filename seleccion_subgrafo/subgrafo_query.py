"""Selecciona el subgrafo de una query proyectando cada entidad con DIAMOnD k + C3 y a continuacion expande la union de todos los modulos con un RWR.

Se hace un solo RWR exacto con la regla de MultiXrank
(../expansion/rwr.py sobre ../manipulacion_grafo/grafo_heterogeneo.py) reinicia uniforme en toda la seleccion, y de cada tipo entran los k_por_tipo nodos de mayor puntaje que todavia no estan. 

"""
import os
import sys
import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, "..", "manipulacion_grafo"))
sys.path.insert(0, os.path.join(_AQUI, "..", "expansion"))

from c3_algoritmo import C3  
from diamond_algoritmo import DIAMOnD  
from diamond_c3_algoritmo import DIAMOnD_C3  
from grafo_heterogeneo import TIPOS, UMBRAL_DRUG, GrafoHeterogeneo, bipartitas   
from planos_y_pasos import (CELDAS, K_POR_PASO, MIN_SEMILLAS, PLANOS, conectar,  
                            obtener_plano, plano_drug)
from rwr import distribucion_uniforme, rwr_exacto  


CACHE_PLANOS = os.path.join(_AQUI, "cache_planos")

SEMILLA_DE_HASH = "42"

ROL_ENTIDAD = "entidad"
ROL_SEMILLA = "semilla"
ROL_VECINO_FUERA_DEL_PLANO = "vecino_fuera_del_plano"
ROL_AGREGADO = "agregado"

#el metodo que figura en la procedencia de un agregado del refinamiento
METODO_REFINAMIENTO = "rwr"

#el paso con el que un grupo BERT entra al subgrafo. no es una celda de CELDAS: el grupo no expande, solo presta
#sus vecinos de la capa B a la entidad
PASO_GRUPO_BERT = "grupo_bert"

#cuantos nodos de cada tipo suma el refinamiento. 
K_POR_TIPO = {"Gene": 9, "Disease": 8, "Drug": 8}

#las configuraciones de la ablacion, cada una con los metodos de agregado que admite ademas de las entidades y los vecinos de la capa B que fueron a buscar
CONFIGURACIONES = {
    "semillas": (),
    "diamond": ("diamond",),
    "diamond_c3": ("diamond", "c3"),
    "completa": ("diamond", "c3", METODO_REFINAMIENTO),
}

#los metodos de expansion de un paso
METODOS = ("diamond", "c3", "diamond_c3")

LABELS = frozenset(plano.tipo for plano in PLANOS.values())

COLUMNAS_NODOS = ["label", "id", "nombre", "procedencias"]
COLUMNAS_ARISTAS = ["label_a", "id_a", "label_b", "id_b", "tipo", "propiedades"]


@dataclass
class Grafo:
    """La conexion a Neo4j. Tiene  los tres planos ya cargados y el grafo heterogeneo donde se hace el RWR."""

    gds: object
    planos: dict[str, object]
    umbral_drug: float
    heterogeneo: object


@dataclass(frozen=True)
class Procedencia:

    #None en los agregados del refinamiento, que no son de una entidad sino de toda la seleccion
    entidad: tuple[str, str] | None
    paso: str | None
    rol: str
    #en un agregado del refinamiento, su puesto dentro de su tipo
    iteracion: int | None = None
    p_valor: float | None = None
    #el algoritmo que agrego el nodo, "diamond", "c3" o "rwr". Queda None si el nodo no es un agregado
    metodo: str | None = None


@dataclass
class Proyeccion:

    entidad: tuple[str, str]
    paso: str | None
    nodos: dict[tuple[str, str], list[Procedencia]]
    expandio: bool


#los nodos de la query con todas sus procedencias, todavia sin aristas
Seleccion = dict[tuple[str, str], list[Procedencia]]


@dataclass
class Subgrafo:
    """Los nodos de la seleccion y las aristas que inducen en el grafo original. Es solo para el return final """

    nodos: pd.DataFrame
    aristas: pd.DataFrame


def cargar_grafo(umbral_drug=UMBRAL_DRUG, verbose=True):
    """Hace la conexion a Neo4j y carga los tres planos y el grafo heterogeneo una sola vez."""

    plano_de_drogas = plano_drug(umbral_drug)
    if os.environ.get("PYTHONHASHSEED") != SEMILLA_DE_HASH:
        warnings.warn(f"PYTHONHASHSEED no vale {SEMILLA_DE_HASH}: los nodos que agregue DIAMOnD pueden "
                      "cambiar de una corrida a otra y no van a coincidir con los de la calibracion")
    gds = conectar()
    planos = {"gene": obtener_plano(gds, PLANOS["gene"], verbose, CACHE_PLANOS),
              "disease": obtener_plano(gds, PLANOS["disease"], verbose, CACHE_PLANOS),
              "drug": obtener_plano(gds, plano_de_drogas, verbose, CACHE_PLANOS)}
    #el heterogeneo se arma con los mismos planos y con las tres relaciones entre tipos, que salen del
    #cache de la carpeta o de Neo4j la primera vez
    heterogeneo = GrafoHeterogeneo([planos["gene"], planos["disease"], planos["drug"]], bipartitas(gds))
    return Grafo(gds, planos, umbral_drug, heterogeneo)


def validar_entidad(G, entidad):
    """Levanta ValueError si la entidad no es un nodo del grafo con ese label."""
    label, id_entidad = entidad
    if label not in LABELS:
        raise ValueError(f"la entidad {entidad} no es de ninguno de los labels {sorted(LABELS)}")
    filas = G.gds.run_cypher(f"MATCH (n:{label} {{id: $id}}) RETURN count(n) AS cuantos",
                             params={"id": id_entidad})
    if not int(filas["cuantos"][0]):
        raise ValueError(f"la entidad {entidad} no esta en el grafo")


def grupos_bert_de(G, entidad):
    """Los ids de los grupos BERT a los que pertenece una entidad enfermedad, todos ordenados. Queda vacio para gen y droga."""
    if entidad[0] != "Disease":
        return []
    filas = G.gds.run_cypher("MATCH (g:Disease)-[:DISEASE_BERT]->(d:Disease {id: $id}) RETURN DISTINCT g.id AS id",
                             params={"id": entidad[1]})
    return sorted(filas["id"])


def cosechar_vecinos_de_entidad(G, entidad, celda):
    """Los ids de los vecinos de la entidad del tipo del plano, sin repetidos y ordenados."""	
    filas = G.gds.run_cypher(
        f"MATCH (a:{celda.origen} {{id: $id}})-[:{celda.relacion_cosecha}]-(b:{celda.tipo_destino}) "
        "RETURN DISTINCT b.id AS id", params={"id": entidad[1]})
    vecinos = set(filas["id"])
    #en el grafo muchas indicaciones cuelgan del grupo BERT de la enfermedad y no de su nodo. Por ejemplo "Parkinson disease" no tiene ninguna arista INDICATION y su grupo tiene 27. la entidad va a buscar tambien los vecinos de sus grupos
    for grupo in grupos_bert_de(G, entidad):
        filas = G.gds.run_cypher(
            f"MATCH (a:{celda.origen} {{id: $id}})-[:{celda.relacion_cosecha}]-(b:{celda.tipo_destino}) "
            "RETURN DISTINCT b.id AS id", params={"id": grupo})
        vecinos.update(filas["id"])
    #no se filtran los grupos BERT
    return sorted(vecinos)


def expandir(red, semillas, n_iter, metodo):
    """[(nodo, metodo que lo agrego, p), ...] en orden de agregado, con el metodo pedido."""
    if metodo == "diamond":
        return [(nodo, "diamond", p) for nodo, _k, _kb, p in DIAMOnD(red, semillas, n_iter)]
    if metodo == "c3":
        agregados, _pasos, _motivo = C3(red, semillas)
        return [(nodo, "c3", p) for nodo, _k, _kb, p in agregados]
    agregados, n_de_diamond, _pasos, _motivo = DIAMOnD_C3(red, semillas, n_iter)
    return [(nodo, "diamond" if i < n_de_diamond else "c3", p)
            for i, (nodo, _k, _kb, p) in enumerate(agregados)]


def proyectar(G, entidad, paso, n_iter, min_semillas=MIN_SEMILLAS, metodo="diamond"):
    """Corre un paso para una determinada entidad: busca sus vecinos y luego expande en el plano con ese metodo."""
    #salvaguardas: 
    if metodo not in METODOS:
        raise ValueError(f"el metodo {metodo!r} no es ninguno de {list(METODOS)}")
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
    #en "c3" n_iter no es un presupuesto, solo dice si el paso expande: los pasos que no figuran en
    #iter_por_paso cosechan sin expandir con cualquier metodo
    expandio = len(semillas) >= min_semillas and n_iter > 0
    if expandio:
        for iteracion, (nodo, de_metodo, p) in enumerate(expandir(red, semillas, n_iter, metodo),
                                                         start=1):
            nodos[(label_destino, nodo)] = [Procedencia(entidad, paso, ROL_AGREGADO, iteracion,
                                                        float(p), de_metodo)]
    return Proyeccion(entidad, paso, nodos, expandio)


def proyectar_heterogeneo(G, entidad, iter_por_paso, min_semillas=MIN_SEMILLAS, metodo="diamond"):
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
        proyeccion = proyectar(G, entidad, paso, iter_por_paso.get(paso, 0), min_semillas, metodo)
        if proyeccion.nodos:
            proyecciones.append(proyeccion)
    #el grupo entra al subgrafo con rol vecino_fuera_del_plano, igual que un vecino de la capa B que no esta en e plano, asi que esta en las cuatro configuraciones. Notar que sin el grupo las drogas que trae quedarian sin ninguna arista hacia la entidad. los grupos solo tienen aristas INDICATION, DISEASE_DISEASE y DISEASE_BERT, asi que en la practica el cambio suma drogas por la celda disease_a_drug
    grupos = grupos_bert_de(G, entidad)
    if grupos:
        nodos = {("Disease", grupo): [Procedencia(entidad, PASO_GRUPO_BERT, ROL_VECINO_FUERA_DEL_PLANO)]
                 for grupo in grupos}
        proyecciones.append(Proyeccion(entidad, PASO_GRUPO_BERT, nodos, False))
    return proyecciones


def unir(proyecciones):
    """Junta las proyecciones en una seleccion, conservando todas las procedencias de cada nodo."""
    seleccion = {}
    for proyeccion in proyecciones:
        for nodo, procedencias in proyeccion.nodos.items():
            seleccion.setdefault(nodo, []).extend(procedencias)
    return seleccion


def refinar(G, seleccion, k_por_tipo=K_POR_TIPO):
    """Suma a la seleccion, de cada tipo, los k_por_tipo nodos de mayor puntaje en un RWR que reinicia en toda ella.

    El RWR es el exacto de ../expansion/rwr.py sobre el grafo heterogeneo, con la regla de
    MultiXrank, y reinicia uniforme en todos los nodos de la seleccion que estan en ese grafo. Los candidatos de
    cada tipo son los nodos que no estan en la seleccion y tienen puntaje positivo; los empates van al indice
    menor. Los agregados entran con rol agregado, metodo rwr, sin entidad y con su puesto en iteracion. Con una
    seleccion vacia en el heterogeneo vuelve sin cambios.
    """
    H = G.heterogeneo
    #los ids van como texto porque asi estan en el heterogeneo
    en_seleccion = H.indices({(label, str(id_nodo)) for label, id_nodo in seleccion})
    if not len(en_seleccion):
        return seleccion
    x = rwr_exacto(H, distribucion_uniforme(H.n, en_seleccion))

    refinada = {nodo: list(procedencias) for nodo, procedencias in seleccion.items()}
    ya_estan = set(en_seleccion.tolist())
    for tipo, k in k_por_tipo.items():
        de_este_tipo = np.flatnonzero(H.tipo == TIPOS.index(tipo))
        candidatos = np.array([v for v in de_este_tipo.tolist() if v not in ya_estan and x[v] > 0], dtype=np.int64)
        #de mayor a menor puntaje; el orden estable deja primero, a igual puntaje, al de indice menor
        elegidos = candidatos[np.argsort(-x[candidatos], kind="stable")][:k]
        for puesto, v in enumerate(elegidos.tolist(), start=1):
            refinada.setdefault(H.nodos[v], []).append(
                Procedencia(None, None, ROL_AGREGADO, iteracion=puesto, metodo=METODO_REFINAMIENTO))
    return refinada


def filtrar_configuracion(seleccion, configuracion):
    """La seleccion con solo las procedencias que admite la configuracion, y solo los nodos que conservan alguna."""
    if configuracion not in CONFIGURACIONES:
        raise ValueError(f"la configuracion {configuracion!r} no es ninguna de {list(CONFIGURACIONES)}")
    metodos = CONFIGURACIONES[configuracion]
    filtrada = {}
    for nodo, procedencias in seleccion.items():
        #las entidades y los vecinos de la capa B que fueron a buscar estan en todas las configuraciones
        quedan = [p for p in procedencias if p.rol != ROL_AGREGADO or p.metodo in metodos]
        if quedan:
            filtrada[nodo] = quedan
    return filtrada


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


def seleccionar(G, entidades, iter_por_paso=K_POR_PASO, min_semillas=MIN_SEMILLAS, metodo="diamond_c3",
                k_por_tipo=K_POR_TIPO):
    """La seleccion refinada de una query: proyecta cada entidad, une las proyecciones y refina con el RWR."""
    proyecciones = [proyeccion for entidad in dict.fromkeys(entidades)
                    for proyeccion in proyectar_heterogeneo(G, entidad, iter_por_paso, min_semillas, metodo)]
    return refinar(G, unir(proyecciones), k_por_tipo)


def obtener_subgrafo_query(G, entidades, iter_por_paso=K_POR_PASO, min_semillas=MIN_SEMILLAS,
                           metodo="diamond_c3", k_por_tipo=K_POR_TIPO, configuracion="completa"):
    """todo el proceso para el subgrafo  de una query: proyecta cada entidad, une, refina y materializa el subgrafo"""
    seleccion = seleccionar(G, entidades, iter_por_paso, min_semillas, metodo, k_por_tipo)
    return materializar_subgrafo(G, filtrar_configuracion(seleccion, configuracion))


def obtener_subgrafos_ablacion(G, entidades, iter_por_paso=K_POR_PASO, min_semillas=MIN_SEMILLAS,
                               k_por_tipo=K_POR_TIPO):
    """{configuracion: Subgrafo} para las cuatro configuraciones de la ablacion, de una sola corrida.

    Todas salen de la misma seleccion refinada, asi que comparten las semillas y los agregados de DIAMOnD y C3, y
    la unica diferencia entre una y la siguiente es la capa que suma.
    """
    seleccion = seleccionar(G, entidades, iter_por_paso, min_semillas, "diamond_c3", k_por_tipo)
    return {configuracion: materializar_subgrafo(G, filtrar_configuracion(seleccion, configuracion))
            for configuracion in CONFIGURACIONES}


if __name__ == "__main__":
    #completar con las entidades de la query como pares (label, id), por ejemplo
    #("Disease", "C0007570") para Celiac Disease. El label es uno de Gene, Disease o Drug y el id
    #es el del nodo en Neo4j
    ENTIDADES = []
    #iteraciones de DIAMOnD por paso, por ejemplo {"disease_a_gene": 100, "disease_a_drug": 20}.
    #Los pasos que no figuran solo cosechan vecinos, sin expandir. Por defecto, las de la calibracion
    #del grafo del laboratorio
    ITER_POR_PASO = K_POR_PASO

    if not ENTIDADES:
        sys.exit("completar ENTIDADES en el main de subgrafo_query.py")

    reloj = time.time()
    grafo = cargar_grafo()
    subgrafo = obtener_subgrafo_query(grafo, ENTIDADES, ITER_POR_PASO)
    print(f"subgrafo: {len(subgrafo.nodos)} nodos y {len(subgrafo.aristas)} aristas "
          f"en {time.time() - reloj:.1f}s")
    print("\nnodos por label:")
    print(subgrafo.nodos["label"].value_counts().to_string())
    print("\naristas por tipo:")
    print(subgrafo.aristas["tipo"].value_counts().to_string())
