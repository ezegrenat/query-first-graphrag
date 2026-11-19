"varias cosas que comparten los scripts de esta carpeta cada script se corre desde esta carpeta con --tarea {factoid|list|yesno|summary} y deja lo suyo en la carpeta de la tarea"
import argparse
import json
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
GRAPHRAG_V2 = os.path.join(AQUI, "..", "..")
CONFIGURACIONES = ["sin_grafo", "grafo_entero", "semillas", "diamond", "diamond_c3", "completa"]
#las de seleccion_subgrafo/subgrafo_query.py, copiadas para correr en la maquina con GPU sin el entorno de la seleccion
SELECCION = ["semillas", "diamond", "diamond_c3", "completa"]
#frase fija de abstencion de la busqueda global
ABSTENCION = "I am sorry but I am unable to answer this question given the provided data"
#el indice del grafo entero con el texto de los nodos 
#texto que llevan los subgrafos de la seleccion
GRAFO_ENTERO = os.path.join(GRAPHRAG_V2, "evaluacion", "grafo_entero",
                            "reportes250_map200_respuesta400_lotes5000_comunidades20_texto", "graphrag")

#el formato de respuesta de cada tarea es el pedido de BioASQ (Ateia y Kruschwitz, 2023, BioASQ 11b)
_ROL_EXACTA = ("You are a biomedical AI expert specializing in question answering and entity extraction. "
               "Answer the following question with its exact answer, using your own knowledge.")
_NOMBRES = (
    "- One name per line. Return ONLY the names: no sentences, no explanations, no headings, no references, no "
    "numbering, no markdown.\n"
    "- Use the shortest standard name of each entity (a gene symbol, a drug name, a disease name). Give each entity "
    "once, with a single name and without synonyms.\n")
_FORMATO_FACTOID = (
    "Return the exact answer only: the names of up to 5 biomedical entities that answer the question, ranked by "
    "confidence, the most likely first. Never exceed 5 names.\n"
    + _NOMBRES +
    "- If no entity answers the question, return only the word: None\n"
    "\n"
    "Example of the expected output:\n"
    "NAME1\n"
    "NAME2")
_FORMATO_LIST = (
    "Return the exact answer only: the names of all the biomedical entities that answer the question, and only those.\n"
    + _NOMBRES +
    "- Do not add entities that are related to the topic but do not answer the question itself.\n"
    "- If no entity answers the question, return only the word: None\n"
    "\n"
    "Example of the expected output:\n"
    "NAME1\n"
    "NAME2\n"
    "NAME3")
_FORMATO_YESNO = (
    "You must answer only with lowercase 'yes' or 'no' even if you are not sure about the answer.\n"
    "Return only that word: no explanations, no references, no punctuation.")
_FORMATO_SUMMARY = (
    "Answer the question by returning a single paragraph-sized text ideally summarizing the most relevant information. "
    "The maximum allowed length of the answer is 200 words. The returned answer is intended to approximate a short text "
    "that a biomedical expert would write to answer the corresponding question (e.g., including prominent supportive "
    "information).\n"
    "Write plain text in one paragraph: no headings, no lists, no references.")


def _con_marca_en_la_lista(formato):
    return formato.replace(
        "no numbering, no markdown.\n",
        "no numbering, no markdown. The only exception is the suffix [LLM: verify] after a name that does not come from the "
        "reports.\n")


TAREAS = {
    "factoid": {"rol": _ROL_EXACTA, "formato": _FORMATO_FACTOID, "con_grafo": _con_marca_en_la_lista(_FORMATO_FACTOID)},
    "list": {"rol": _ROL_EXACTA, "formato": _FORMATO_LIST, "con_grafo": _con_marca_en_la_lista(_FORMATO_LIST)},
    "yesno": {"rol": "You are a biomedical AI expert who answers yes or no questions, using your own knowledge.",
              "formato": _FORMATO_YESNO,
              "con_grafo": _FORMATO_YESNO + " The only exception is the suffix [LLM: verify] when the answer does not "
                                            "come from the reports."},
    "summary": {"rol": "You are a biomedical AI expert who answers questions with a short summary, using your own "
                       "knowledge.",
                "formato": _FORMATO_SUMMARY,
                "con_grafo": _FORMATO_SUMMARY + " The only exception is the tag [LLM: verify] after information that does "
                                                "not come from the reports."},
}
#las preguntas de factoid cuya respuesta no tiene nodo en el grafo (preguntas/armar_conjunto_sin_oro.ipynb): la
#misma tarea con su propia carpeta y su propia muestra, para no mezclar respuestas con las de factoid
TAREAS["factoid_sin_oro"] = TAREAS["factoid"]
#las preguntas de list partidas por cuanto del oro tiene nodo en el grafo entero (preguntas/armar_conjunto_list_por_oro.ipynb):
#la misma tarea con su propia carpeta y su propia muestra, para no mezclar respuestas con las de list
TAREAS["list_por_oro"] = TAREAS["list"]

#el prompt del reduce de cada tarea. factoid y list comparten el de la respuesta exacta
REDUCE = {"factoid": "reduce_exacta.txt", "factoid_sin_oro": "reduce_exacta.txt", "list": "reduce_exacta.txt",
          "list_por_oro": "reduce_exacta.txt", "yesno": "reduce_yesno.txt", "summary": "reduce_summary.txt"}


def reduce_de(tarea):
    return os.path.join(AQUI, "prompts", REDUCE[tarea])


def prompt_sin_grafo(tarea):
    return TAREAS[tarea]["rol"] + "\n\n" + TAREAS[tarea]["formato"] + "\n\nQuestion: {pregunta}"


def cargar_env():
    "las variables del .env del pipeline (neo4j, binarios de graphrag) sin pisar las ya definidas, y graphrag/ en el path"
    with open(os.path.join(GRAPHRAG_V2, ".env")) as archivo:
        for linea in archivo:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                os.environ.setdefault(clave.strip(), valor.strip())
    sys.path.insert(0, os.path.join(GRAPHRAG_V2, "graphrag"))


def argumentos(parser=None):
    parser = parser or argparse.ArgumentParser()
    parser.add_argument("--tarea", required=True, choices=list(TAREAS))
    return parser.parse_args()


def carpeta_de(tarea):
    return os.path.join(AQUI, tarea)


def muestra_de(tarea):
    with open(os.path.join(AQUI, "preguntas", f"muestra_{tarea}.json")) as archivo:
        return json.load(archivo)


def claves_de(tarea):
    "la clave del conjunto de entidades de cada pregunta de la muestra, que deja seleccionar.py"
    with open(os.path.join(carpeta_de(tarea), "claves.json")) as archivo:
        return json.load(archivo)


#las respuestas de summary tal como se miden: sin la marca de modo abierto ni las citas de graphrag, y sin abstenciones.

REPETICIONES = 3
MARCA = re.compile(r"\s*[\[(]\s*LLM:?\s*verify\s*[\])]", re.IGNORECASE)


def limpiar(texto):
    "la respuesta sin la marca ni las citas de graphrag"
    return re.sub(r"\[Data:[^\]]*\]", " ", MARCA.sub(" ", texto)).strip()


def respuestas_de(muestra):
    "las respuestas con codigo 0 que haya en disco, sin las abstenciones"
    filas = []
    for rep in range(1, REPETICIONES + 1):
        for consulta in muestra:
            for configuracion in CONFIGURACIONES:
                ruta = os.path.join(carpeta_de("summary"), "respuestas", f"rep{rep}", consulta, configuracion, "respuesta.json")
                if not os.path.exists(ruta):
                    continue
                with open(ruta) as archivo:
                    respuesta = json.load(archivo)
                if respuesta["codigo"] != 0 or ABSTENCION in respuesta["respuesta"]:
                    continue
                filas.append({"rep": rep, "consulta": consulta, "configuracion": configuracion,
                              "respuesta": limpiar(respuesta["respuesta"])})
    import pandas as pd
    return pd.DataFrame(filas)


