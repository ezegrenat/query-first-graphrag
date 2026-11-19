
import hashlib
import json
import os
import sys
import time

from comun import GRAPHRAG_V2, argumentos, carpeta_de, cargar_env, muestra_de

PARAMETROS = {"largo_reportes": 250, "largo_map": 200, "largo_respuesta": 400, "contexto_map": 5000,
              "tamano_comunidad": 20, "con_texto": True}

cargar_env()
sys.path.insert(0, os.path.join(GRAPHRAG_V2, "seleccion_subgrafo"))
from pipeline import preparar  # noqa: E402
from subgrafo_query import SEMILLA_DE_HASH  # noqa: E402

assert os.environ.get("PYTHONHASHSEED") == SEMILLA_DE_HASH, "correr con PYTHONHASHSEED=42"


def clave_de(entidades):
    """El nombre de la carpeta de un conjunto de entidades: sus label e id ordenados. Si es muy largo para una carpeta,
    los primeros 100 caracteres y un hash del resto."""
    clave = "__".join(f"{label}_{id_nodo}" for label, id_nodo in sorted(tuple(e) for e in entidades))
    if len(clave) > 150:
        clave = clave[:100] + "_" + hashlib.md5(clave.encode()).hexdigest()[:8]
    return clave


tarea = argumentos().tarea
carpeta = carpeta_de(tarea)
os.makedirs(carpeta, exist_ok=True)

#un conjunto de entidades por clave, con la primera pregunta que lo nombra
claves, conjuntos = {}, {}
for nombre, consulta in muestra_de(tarea).items():
    clave = clave_de(consulta["entidades"])
    claves[nombre] = clave
    if clave not in conjuntos:
        conjuntos[clave] = {"pregunta": consulta["pregunta"], "entidades": consulta["entidades"]}
with open(os.path.join(carpeta, "claves.json"), "w") as archivo:
    json.dump(claves, archivo, indent=1)
print(len(claves), "preguntas,", len(conjuntos), "conjuntos de entidades", flush=True)

resultados = os.path.join(carpeta, "indices")
os.makedirs(resultados, exist_ok=True)
reloj = time.time()
preparar(list(conjuntos), conjuntos, resultados, PARAMETROS)
print(f"{len(conjuntos)} conjuntos en {resultados}, {time.time() - reloj:.0f} s")
