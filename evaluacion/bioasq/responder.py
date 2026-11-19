"""pide las respuestas de la muestra de una tarea a las seis configuraciones. las deja en {tarea}/respuestas/rep{n}/ y saltea lo que ya esta respondido"""
#necesita el Ollama de la GPU (OLLAMA_GPU en graphrag/rag/llm.py)
#python responder.py --tarea summary --rep 1
import argparse
import json
import os
import sys

from comun import ABSTENCION, CONFIGURACIONES, GRAFO_ENTERO, TAREAS, argumentos, carpeta_de, cargar_env, claves_de, \
    muestra_de, prompt_sin_grafo, reduce_de

cargar_env()
from rag.graphrag_msft import MAX_TOKENS_RESPUESTAS, consultar_proyecto, ya_respondida  # noqa: E402
from rag.llm import MODELOS, generar  # noqa: E402

NIVEL = 0

parser = argparse.ArgumentParser()
parser.add_argument("--rep", required=True, type=int, help="numero de repeticion, de 1 en adelante")
parser.add_argument("--solo-listos", action="store_true", help="saltear sin error las configuraciones sin indice")
parser.add_argument("--preguntas", type=int, default=None, help="responder solo las primeras N preguntas de la muestra")
args = argumentos(parser)

carpeta = carpeta_de(args.tarea)
muestra = muestra_de(args.tarea)
claves = claves_de(args.tarea)
if args.preguntas:
    muestra = dict(list(muestra.items())[:args.preguntas])
sin_grafo = prompt_sin_grafo(args.tarea)
con_grafo = TAREAS[args.tarea]["con_grafo"]
reduce = reduce_de(args.tarea)

errores, pendientes = 0, 0
for nombre, consulta in muestra.items():
    pregunta = consulta["pregunta"]
    for configuracion in CONFIGURACIONES:
        destino = os.path.join(carpeta, "respuestas", f"rep{args.rep}", nombre, configuracion)
        ruta = os.path.join(destino, "respuesta.json")
        if ya_respondida(ruta):
            continue

        if configuracion == "sin_grafo":
            try:
                respuesta, llamada = generar(MODELOS["graphrag"], sin_grafo.format(pregunta=pregunta),
                                             max_tokens=MAX_TOKENS_RESPUESTAS)
            except OSError as error:
                errores += 1
                print(f"[{nombre} sin_grafo] error {error}", flush=True)
                continue
            os.makedirs(destino, exist_ok=True)
            with open(ruta, "w") as archivo:
                json.dump({"pregunta": pregunta, "respuesta": respuesta, "codigo": 0, **llamada}, archivo, indent=1,
                          ensure_ascii=False)
            continue

        if configuracion == "grafo_entero":
            proyecto = GRAFO_ENTERO
        else:
            indices = os.path.join(carpeta, "indices", claves[nombre], configuracion)
            ruta_indice = os.path.join(indices, "indice.json")
            if not os.path.exists(ruta_indice):
                if args.solo_listos:
                    pendientes += 1
                else:
                    errores += 1
                    print(f"[{nombre} {configuracion}] sin indice", flush=True)
                continue
            with open(ruta_indice) as archivo:
                indice = json.load(archivo)
            #un subgrafo sin aristas no tiene indice: la configuracion no tiene con que responder y se abstiene
            if indice.get("vacio"):
                os.makedirs(destino, exist_ok=True)
                with open(ruta, "w") as archivo:
                    json.dump({"pregunta": pregunta, "respuesta": ABSTENCION, "codigo": 0, "subgrafo_vacio": True},
                              archivo, indent=1)
                continue
            if indice["codigo"] != 0:
                errores += 1
                print(f"[{nombre} {configuracion}] indice con error", flush=True)
                continue
            proyecto = os.path.join(indices, "graphrag")
        os.makedirs(destino, exist_ok=True)
        resultado = consultar_proyecto(proyecto, pregunta, ruta, "global", NIVEL, "prosa",
                                       tipo_respuesta=con_grafo, reduce=reduce, memoria=True)
        if resultado["codigo"] != 0:
            errores += 1
        print(f"[{nombre} {configuracion}] codigo {resultado['codigo']} en {resultado['segundos']:.0f} s", flush=True)

print(f"rep {args.rep}: {len(muestra)} consultas, {errores} con error, {pendientes} esperando indice", flush=True)
sys.exit(1 if errores else 0)
