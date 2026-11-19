"""la carpeta de resultados, el cache de planos y las variantes que se eligen por entorno (CRECIMIENTO_*). es lo que la calibracion le suma a los planos y las celdas de manipulacion_grafo/planos_y_pasos.py"""
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, "..", "manipulacion_grafo"))

import planos_y_pasos  # noqa: E402
from planos_y_pasos import plano_disease, plano_drug  # noqa: E402


RESULTADOS = os.path.join(_AQUI, os.environ.get("CRECIMIENTO_RESULTADOS", "resultados_grafo_laboratorio"))
CACHE_PLANOS = os.path.join(RESULTADOS, "cache_planos")

GRUPOS_BERT = os.environ.get("CRECIMIENTO_GRUPOS_BERT", "excluidos")
if GRUPOS_BERT not in ("excluidos", "incluidos"):
    raise ValueError(f"CRECIMIENTO_GRUPOS_BERT tiene que ser excluidos o incluidos, no {GRUPOS_BERT!r}")

#la similaridad minima para que dos drogas esten unidas en el plano drug
UMBRAL_DRUG = float(os.environ.get("CRECIMIENTO_UMBRAL_DRUG", "0.8"))

#los planos de esta corrida: los de planos_y_pasos con las dos variantes elegidas por entorno
PLANOS = dict(planos_y_pasos.PLANOS)
PLANOS["disease"] = plano_disease(con_grupos_bert=GRUPOS_BERT == "incluidos")
PLANOS["drug"] = plano_drug(UMBRAL_DRUG)

#las celdas que sortean menos entidades por bin que el resto. con los compuestos del laboratorio
#ninguna celda baja de 205 entidades elegibles, asi que todas sortean CRECIMIENTO_N_POR_BIN.
#Con otro grafo o con otro umbral del plano drug puede cambiar el pool de una celda, y el dato
#se reemplaza por entorno: CRECIMIENTO_N_POR_BIN_CELDA=disease_a_drug=38,gene_a_drug=5
N_POR_BIN_POR_CELDA = {}
_por_entorno = os.environ.get("CRECIMIENTO_N_POR_BIN_CELDA", "")
if _por_entorno:
    N_POR_BIN_POR_CELDA = {}
    for _par in _por_entorno.split(","):
        _celda, _n = _par.split("=")
        N_POR_BIN_POR_CELDA[_celda.strip()] = int(_n)


def obtener_plano(gds, plano, verbose=True, cache_dir=CACHE_PLANOS):
    """obtener_plano de planos_y_pasos, con el cache de esta corrida por defecto."""
    return planos_y_pasos.obtener_plano(gds, plano, verbose, cache_dir)


def nodos_que_no_pueden_ser_semilla(gds, plano):
    if plano.tipo == "Disease" and GRUPOS_BERT == "incluidos":
        filas = gds.run_cypher("MATCH (d:Disease) WHERE d.es_grupo_bert RETURN d.id AS id")
        return frozenset(filas["id"])
    return frozenset()
