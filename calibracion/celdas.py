"""Los planos homogeneos y las celdas del experimento sobre PrimeKG integrado.

Es la version para PrimeKG integrado (PrimeKG para enfermedades, DisGeNET, HIPPIE, SIGNOR,
Reactome) del celdas.py de optimuskg/experimentacion_proyeccion. Misma idea y misma interfaz:
una celda es un paso del algoritmo de seleccion de subgrafo: dada una entidad de la consulta de
tipo A, se va a buscar sus vecinos de tipo B por la relacion que une A con B, y se corre DIAMOnD
dentro del plano B-B. El salto entre tipos lo hace la busqueda de vecinos; DIAMOnD nunca cambia
de tipo.

Que cambia respecto de OptimusKG:
- Dos tipos en vez de cuatro, {Disease, Gene}, y solo las celdas cruzadas: 2 celdas en vez de
  16, una por plano. Las celdas del mismo tipo (gene_a_gene, disease_a_disease) quedan fuera por
  decision del 2026-09-10: el experimento mide proyecciones entre capas, no dentro de una capa.
  Pathway queda fuera por la misma decision, y drogas y fenotipos no estan en este grafo.
- No hay umbral de evidencia: las asociaciones gen-enfermedad son las curadas de DisGeNET y no
  traen score. Tampoco hay is_truly_disease.
- Los grupos BERT (1.040 nodos Disease con es_grupo_bert, hubs artificiales que unen sinonimos)
  quedan fuera de todo el analisis, decision del 2026-09-10: no son anclas, no son semillas y no
  estan en el plano de enfermedades. Tampoco entra la estrella DISEASE_BERT que los une con sus
  miembros; el plano disease es solo la jerarquia padre-hijo de MONDO.
- Los ids son la propiedad `id` de Neo4j, que en este grafo es el id de origen: Entrez para
  genes y CUI de UMLS para enfermedades.

Este es el unico modulo del experimento que habla con Neo4j (el contenedor neo4j-thesis).
"""
import os
import sys
from dataclasses import dataclass

#config vive en la carpeta del grafo y la red compacta en expansion/. El sys.path se arregla
#antes del import, por eso el noqa
_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, "..", "grafos", "primekg_integrado", "neo4j"))
sys.path.insert(0, os.path.join(_AQUI, "..", "expansion"))

import config  # noqa: E402
from graphdatascience import GraphDataScience  # noqa: E402

from adyacencia import RedCompacta, construir_red  # noqa: E402

#el directorio de salida es configurable para que una corrida variante escriba aparte sin tocar
#la principal. Una ruta relativa se interpreta respecto de esta carpeta
RESULTADOS = os.path.join(_AQUI, os.environ.get("CRECIMIENTO_RESULTADOS", "resultados"))
CACHE_PLANOS = os.path.join(RESULTADOS, "cache_planos")

#minimo de semillas efectivas para que un ancla entre en el experimento
MIN_SEMILLAS = 5

#los dos tipos del alcance. El orden es el de las filas de las figuras y el de las celdas
#dentro de cada plano
TIPOS = ("Disease", "Gene")

#el filtro que deja a los grupos BERT fuera del plano de enfermedades y de las anclas
SIN_GRUPOS_BERT = "NOT a.es_grupo_bert AND NOT b.es_grupo_bert"

#si los grupos BERT estan en el plano de enfermedades. Se elige por variable de entorno para correr
#las dos versiones con el mismo codigo, cada una en su propia carpeta de resultados. excluidos es la
#version del primer batch (2026-09-10), incluidos es el grafo tal cual, con la estrella
GRUPOS_BERT = os.environ.get("CRECIMIENTO_GRUPOS_BERT", "excluidos")
if GRUPOS_BERT not in ("excluidos", "incluidos"):
    raise ValueError(f"CRECIMIENTO_GRUPOS_BERT tiene que ser excluidos o incluidos, no {GRUPOS_BERT!r}")


@dataclass(frozen=True)
class Plano:
    """La red homogenea de un tipo de nodo: donde corre DIAMOnD.

    `filtro_cypher` es un predicado sobre los extremos de la arista que se le pasa a
    `construir_red`, o None si el plano se toma entero. `relacion` puede juntar varias relaciones
    con "|", como en el plano de enfermedades con los grupos BERT.
    """

    nombre: str
    tipo: str
    relacion: str
    filtro_cypher: str | None = None

    def __repr__(self):
        return f"<Plano {self.nombre}: {self.tipo}-{self.tipo} via {self.relacion}>"


PLANOS = {
    #el interactoma de HIPPIE. FORM_COMPLEX (complejos de SIGNOR) queda fuera para conservar una
    #sola relacion por plano
    "gene": Plano("gene", "Gene", "PPI"),
}
if GRUPOS_BERT == "excluidos":
    #la jerarquia padre-hijo de MONDO, sin los grupos BERT
    PLANOS["disease"] = Plano("disease", "Disease", "DISEASE_DISEASE", filtro_cypher=SIN_GRUPOS_BERT)
else:
    #el plano tal cual viene en el grafo: MONDO mas la estrella que une cada grupo con sus miembros
    PLANOS["disease"] = Plano("disease", "Disease", "DISEASE_DISEASE|DISEASE_BERT")


@dataclass(frozen=True)
class Celda:
    """Un paso del algoritmo: buscar los vecinos desde un tipo de origen y expandir en un plano."""

    nombre: str
    origen: str            #label del ancla
    plano: str             #nombre del plano donde corre DIAMOnD
    relacion_cosecha: str  #la relacion por la que el ancla llega a sus vecinos de la capa B
    cypher_cosecha: str
    evidencia_minima: float | None = None   #sin uso en este grafo; se conserva por la interfaz

    @property
    def tipo_destino(self):
        """El label de los nodos del plano, que es tambien el de las semillas."""
        return PLANOS[self.plano].tipo

    @property
    def ancla_en_la_red(self):
        """Si el ancla pertenece al plano donde se corre. Siempre falso en esta version, porque
        solo hay celdas cruzadas: el ancla es de otro tipo y no esta en la red. Se conserva por
        la interfaz con corrida.py y paso2_runner.py, que excluyen el ancla de la red cuando es verdadero."""
        return self.origen == self.tipo_destino

    def __repr__(self):
        return (f"<Celda {self.nombre}: ancla {self.origen}, vecinos por "
                f"{self.relacion_cosecha}, expande en el plano {self.plano}>")


def nombre_celda(origen, plano):
    """El nombre de la celda que va del tipo de origen al plano, por ejemplo disease_a_gene."""
    return f"{origen.lower()}_a_{plano}"


#Las dos consultas, una por celda y escritas completas. Todas devuelven las mismas dos
#columnas: ancla (el nodo de la consulta) y semilla (un vecino del tipo del plano). Los grupos
#BERT se excluyen explicitamente de cualquier extremo que toque la capa Disease, aunque no tengan
#aristas GDA (no las tienen), para que la regla se lea en la consulta y no dependa de los datos.
COSECHA = {
    #Disease como ancla
    "disease_a_gene": (
        "MATCH (a:Disease)-[r:GDA]-(b:Gene) "
        "WHERE NOT a.es_grupo_bert "
        "RETURN a.id AS ancla, b.id AS semilla"),

    #Gene como ancla
    "gene_a_disease": (
        "MATCH (a:Gene)-[r:GDA]-(b:Disease) "
        "WHERE NOT b.es_grupo_bert "
        "RETURN a.id AS ancla, b.id AS semilla"),
}


#Las dos celdas, escritas una por una
CELDAS = {
    "disease_a_gene": Celda(
        "disease_a_gene", "Disease", "gene", "GDA",
        COSECHA["disease_a_gene"]),
    "gene_a_disease": Celda(
        "gene_a_disease", "Gene", "disease", "GDA",
        COSECHA["gene_a_disease"]),
}


#las celdas de cada plano (una sola, la cruzada), en el orden de TIPOS. Se deriva de CELDAS y no
#de TIPOS x PLANOS porque no todas las combinaciones existen
CELDAS_POR_PLANO = {}
for _plano in PLANOS:
    CELDAS_POR_PLANO[_plano] = [nombre_celda(_origen, _plano) for _origen in TIPOS
                                if nombre_celda(_origen, _plano) in CELDAS]

#el orden del batch y de las tablas: plano por plano, y dentro de cada plano por tipo de origen
ORDEN_CELDAS = []
for _plano in PLANOS:
    ORDEN_CELDAS.extend(CELDAS_POR_PLANO[_plano])


def conectar():
    """Cliente GDS contra neo4j-thesis, con las credenciales de ../neo4j/config.py."""
    return GraphDataScience(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))


def obtener_plano(gds, plano, verbose=True, cache_dir=CACHE_PLANOS):
    """La red homogenea del plano, del cache .npz si existe y de Neo4j si no.

    `construir_red` con un solo tipo de nodo trae las aristas internas de ese tipo, y devuelve la
    red ya simetrizada, binarizada y sin autoloops, que es lo que DIAMOnD espera.
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


def nodos_que_no_pueden_ser_semilla(gds, plano):
    """Ids del plano que ninguna celda trae como semilla y que por eso tampoco se sortean como semilla de control: los grupos BERT, cuando estan en el plano de enfermedades."""
    if plano.tipo == "Disease" and GRUPOS_BERT == "incluidos":
        filas = gds.run_cypher("MATCH (d:Disease) WHERE d.es_grupo_bert RETURN d.id AS id")
        return frozenset(filas["id"])
    return frozenset()


def cosechar(gds, celda):
    """Todos los pares (ancla, semilla) de la consulta de la celda, como DataFrame.

    Es la capa bipartita de la celda con sus filtros ya aplicados, sin restringir todavia al
    plano donde corre DIAMOnD. Se llama asi por compatibilidad con el resto de los modulos.
    """
    return gds.run_cypher(celda.cypher_cosecha)


def semillas_efectivas(gds, celda, red):
    """{ancla: [semillas presentes en el plano]}, todas las anclas de una vez.

    Una semilla cuenta solo si existe en el plano donde va a correr DIAMOnD: un gen sin ninguna
    interaccion en HIPPIE no puede sembrar en el plano gene aunque tenga asociaciones.
    """
    filas = cosechar(gds, celda)

    en_el_plano = set(red.nodes())
    por_ancla = {}
    for ancla, semilla in zip(filas["ancla"], filas["semilla"]):
        if semilla in en_el_plano:
            por_ancla.setdefault(ancla, set()).add(semilla)

    #el ancla no puede ser semilla de si misma. Las consultas de las celdas del mismo tipo ya lo
    #excluyen con a.id <> b.id, y esto lo vuelve a garantizar para cualquier celda
    resultado = {}
    for ancla, semillas in por_ancla.items():
        sin_el_ancla = sorted(semillas - {ancla})
        if sin_el_ancla:
            resultado[ancla] = sin_el_ancla
    return resultado


def nombres_por_id(gds, ids, label):
    """{id: nombre legible} para los reportes. Todos los ids tienen que ser del mismo label."""
    if not ids:
        return {}
    filas = gds.run_cypher(f"MATCH (n:`{label}`) WHERE n.id IN $ids "
                           "RETURN n.id AS id, n.name AS nombre",
                           params={"ids": list(ids)})
    return dict(zip(filas["id"], filas["nombre"]))
