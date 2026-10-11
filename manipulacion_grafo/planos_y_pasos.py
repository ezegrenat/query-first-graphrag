"""Los planos homogeneos, los pasos (las celdas de la calibracion) y las consultas al grafo de PrimeKG integrado

son tres planos y seis celdas cruzadas. Las celdas del mismo tipo quedan fuera (no se expande ahi) 

"""
import os
import sys
from dataclasses import dataclass

#config esta en la carpeta del grafo y la red compacta en expansion/
_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, "..", "grafos", "primekg_integrado", "neo4j"))
sys.path.insert(0, os.path.join(_AQUI, "..", "expansion"))

import config  
from graphdatascience import GraphDataScience  

from adyacencia import RedCompacta, construir_red  

#minimo de semillas efectivas para que una entidad entre en el experimento
MIN_SEMILLAS = 5

#los tres tipos del alcance:
TIPOS = ("Disease", "Gene", "Drug")

#el filtro que deja a los grupos BERT fuera del plano de enfermedades y de las entidades
SIN_GRUPOS_BERT = "NOT a.es_grupo_bert AND NOT b.es_grupo_bert"

#el corte mas bajo con sentido para el plano drug: las aristas DRUG_DRUG del laboratorio arrancan
#en 0,81, asi que con 0,8 entran todas y un corte menor diria que hay aristas que no estan cargadas
UMBRAL_DRUG_MINIMO = 0.8


@dataclass(frozen=True)
class Plano:
    """La red homogenea de un tipo de nodo"""

    nombre: str
    tipo: str
    relacion: str
    filtro_cypher: str | None = None

    def __repr__(self):
        return f"<Plano {self.nombre}: {self.tipo}-{self.tipo} via {self.relacion}>"


def plano_disease(con_grupos_bert=False):
    if con_grupos_bert:
        return Plano("disease_con_grupos_bert", "Disease", "DISEASE_DISEASE|DISEASE_BERT")
    return Plano("disease", "Disease", "DISEASE_DISEASE", filtro_cypher=SIN_GRUPOS_BERT)


def plano_drug(umbral=UMBRAL_DRUG_MINIMO):
    if not UMBRAL_DRUG_MINIMO <= umbral <= 1.0:
        raise ValueError(f"DRUG_DRUG arranca en 0,81 en Neo4j, asi que el umbral del plano drug "
                         f"tiene que estar entre {UMBRAL_DRUG_MINIMO} y 1.0, no {umbral}")
    return Plano(f"drug_u{int(round(umbral * 100)):03d}", "Drug", "DRUG_DRUG",
                 filtro_cypher=f"r.weight >= {umbral}")

PLANOS = {
    "gene": Plano("gene", "Gene", "PPI"),
    "disease": plano_disease(),
    "drug": plano_drug(),
}


@dataclass(frozen=True)
class Celda:
    """buscar los vecinos desde un tipo de origen y expandir en un plano."""

    nombre: str
    origen: str            #label de la entidad
    plano: str             #nombre del plano donde corre DIAMOnD
    relacion_cosecha: str  #la relacion por la que la entidad llega a sus vecinos de la capa B
    cypher_cosecha: str
    evidencia_minima: float | None = None   #no se esta usando

    @property
    def tipo_destino(self):
        return PLANOS[self.plano].tipo

    @property
    def entidad_en_la_red(self):
        """Si la entidad pertenece al plano donde se corre. Siempre falso en esta version, porque solo hay celdas cruzadas. Se conserva por si se pasa a considerar expansiones intra capa eventualmente"""
        return self.origen == self.tipo_destino

    def __repr__(self):
        return (f"<Celda {self.nombre}: entidad {self.origen}, vecinos por "
                f"{self.relacion_cosecha}, expande en el plano {self.plano}>")


def nombre_celda(origen, plano):
    """El nombre de la celda que va del tipo de origen al plano en formato facil de leer, por ejemplo disease_a_gene"""
    return f"{origen.lower()}_a_{plano}"


#Las seis consultas, una por celda y escritas completas. BERT se excluyen explicitamente de cualquier extremo que toque la capa Disease, aunque no tengan #aristas GDA 

COSECHA = {
    #Disease como entidad
    "disease_a_gene": (
        "MATCH (a:Disease)-[r:GDA]-(b:Gene) "
        "WHERE NOT a.es_grupo_bert "
        "RETURN a.id AS entidad, b.id AS semilla"),

    #Gene como entidad
    "gene_a_disease": (
        "MATCH (a:Gene)-[r:GDA]-(b:Disease) "
        "WHERE NOT b.es_grupo_bert "
        "RETURN a.id AS entidad, b.id AS semilla"),

    #drogas como entidad
    "drug_a_gene": (
        "MATCH (a:Drug)-[r:DRUG_TARGET]-(b:Gene) "
        "RETURN a.id AS entidad, b.id AS semilla"),
    "drug_a_disease": (
        "MATCH (a:Drug)-[r:INDICATION]-(b:Disease) "
        "WHERE NOT b.es_grupo_bert "
        "RETURN a.id AS entidad, b.id AS semilla"),

    #Disease y Gene como entidad, con DIAMOnD en el plano de drogas
    "disease_a_drug": (
        "MATCH (a:Disease)-[r:INDICATION]-(b:Drug) "
        "WHERE NOT a.es_grupo_bert "
        "RETURN a.id AS entidad, b.id AS semilla"),
    "gene_a_drug": (
        "MATCH (a:Gene)-[r:DRUG_TARGET]-(b:Drug) "
        "RETURN a.id AS entidad, b.id AS semilla"),
}


#Las seis celdas, escritas una por una
CELDAS = {
    "disease_a_gene": Celda(
        "disease_a_gene", "Disease", "gene", "GDA",
        COSECHA["disease_a_gene"]),
    "gene_a_disease": Celda(
        "gene_a_disease", "Gene", "disease", "GDA",
        COSECHA["gene_a_disease"]),
    "drug_a_gene": Celda(
        "drug_a_gene", "Drug", "gene", "DRUG_TARGET",
        COSECHA["drug_a_gene"]),
    "drug_a_disease": Celda(
        "drug_a_disease", "Drug", "disease", "INDICATION",
        COSECHA["drug_a_disease"]),
    "disease_a_drug": Celda(
        "disease_a_drug", "Disease", "drug", "INDICATION",
        COSECHA["disease_a_drug"]),
    "gene_a_drug": Celda(
        "gene_a_drug", "Gene", "drug", "DRUG_TARGET",
        COSECHA["gene_a_drug"]),
}


#iteraciones de DIAMOnD por paso para la opcion "DIAMOnD k + C3". Los valores son elegidos mirando el recall medio con el 30% escondido de la calibracion del grafo del laboratorio 

K_POR_PASO = {
    "disease_a_gene": 40,   
    "drug_a_gene": 10,      
    "gene_a_disease": 50,   
    "drug_a_disease": 30,   
    "disease_a_drug": 25,   
    "gene_a_drug": 10,      
}


CELDAS_POR_PLANO = {}
for _plano in PLANOS:
    CELDAS_POR_PLANO[_plano] = [nombre_celda(_origen, _plano) for _origen in TIPOS
                                if nombre_celda(_origen, _plano) in CELDAS]


ORDEN_CELDAS = []
for _plano in PLANOS:
    ORDEN_CELDAS.extend(CELDAS_POR_PLANO[_plano])


def conectar():
    """Cliente GDS contra neo4j-thesis con las credenciales de ../grafos/primekg_integrado/neo4j/config.py."""
    return GraphDataScience(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))


def obtener_plano(gds, plano, verbose, cache_dir):
    """La red homogenea del plano sacandola  del cache .npz si existe y de Neo4j si no.

    `construir_red` con un solo tipo de nodo trae las aristas internas de ese tipo, y devuelve la red ya simetrizada, binarizada y sin autoloops, que es lo que DIAMOnD espera.
    """
    os.makedirs(cache_dir, exist_ok=True)
    ruta = os.path.join(cache_dir, plano.nombre)
    if os.path.exists(f"{ruta}.npz"):
        red = RedCompacta.cargar(ruta)
    else:
        red = construir_red(gds, [plano.tipo], plano.relacion.split("|"), verbose=verbose,
                            filtro_cypher=plano.filtro_cypher)
        red.guardar(ruta)
    if verbose:
        print(f"[plano {plano.nombre}] {red.number_of_nodes():,} nodos, "
              f"{red.number_of_edges():,} aristas")
    return red


def cosechar(gds, celda):
    """Todos los pares (entidad, semilla) de la consulta de la celda como DataFrame.
    Es la capa bipartita de la celda con sus filtros ya aplicados
    """
    return gds.run_cypher(celda.cypher_cosecha)


def semillas_efectivas(gds, celda, red):
    """{entidad: [semillas presentes en el plano]}, todas las entidades de una vez.

    Una semilla cuenta solo si existe en el plano donde va a correr DIAMOnD: un gen sin ninguna interaccion en HIPPIE no puede sembrar en el plano gene aunque tenga asociaciones.
    """
    filas = cosechar(gds, celda)

    en_el_plano = set(red.nodes())
    por_entidad = {}
    for entidad, semilla in zip(filas["entidad"], filas["semilla"]):
        if semilla in en_el_plano:
            por_entidad.setdefault(entidad, set()).add(semilla)

    #la entidad no puede ser semilla de si misma
    resultado = {}
    for entidad, semillas in por_entidad.items():
        sin_la_entidad = sorted(semillas - {entidad})
        if sin_la_entidad:
            resultado[entidad] = sin_la_entidad
    return resultado


def nombres_por_id(gds, ids, label):
    """{id: nombre legible} para los reportes. Todos los ids tienen que ser del mismo label."""
    if not ids:
        return {}
    filas = gds.run_cypher(f"MATCH (n:`{label}`) WHERE n.id IN $ids "
                           "RETURN n.id AS id, n.name AS nombre",
                           params={"ids": list(ids)})
    return dict(zip(filas["id"], filas["nombre"]))
