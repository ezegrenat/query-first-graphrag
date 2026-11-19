"""cuanto cuesta linkear_entidades (../../../graphrag/entidades/linkear_entidades.py) en las preguntas de una muestra"""
# python medir_enlace.py --tarea factoid

import argparse
import json
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..", "..", "graphrag"))
from entidades.linkear_entidades import MODELO, PROMPT, Linkeador, menciones_de  # noqa: E402
from rag.llm import generar  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--tarea", required=True, choices=["factoid", "list", "yesno", "summary"])
argumentos = parser.parse_args()

with open(os.path.join(AQUI, f"muestra_{argumentos.tarea}.json")) as archivo:
    muestra = json.load(archivo)
with open(PROMPT) as archivo:
    plantilla = archivo.read()

reloj = time.perf_counter()
linkeador = Linkeador()
segundos_linkeador = round(time.perf_counter() - reloj, 2)
print(f"Linkeador armado en {segundos_linkeador} s", flush=True)

preguntas = {}
for n, (nombre, consulta) in enumerate(muestra.items(), start=1):
    #el prompt tiene llaves de JSON en los ejemplos, por eso se reemplaza en lugar de usar format
    prompt = plantilla.replace("{pregunta}", consulta["pregunta"])
    respuesta, datos = generar(MODELO, prompt, formato_json=True)

    reloj = time.perf_counter()
    entidades = []
    for mencion in menciones_de(respuesta):
        enlace = linkeador.linkear_mencion(mencion)
        if enlace:
            entidades.extend((enlace[0], id_nodo) for id_nodo in enlace[1])
    segundos_enlace = time.perf_counter() - reloj

    preguntas[nombre] = {"tokens_entrada": datos["tokens_entrada"], "tokens_salida": datos["tokens_salida"],
                         "segundos_deteccion": datos["segundos"], "segundos_enlace": round(segundos_enlace, 4),
                         "mismas_entidades": set(entidades) == {tuple(e) for e in consulta["entidades"]}}
    if n % 20 == 0:
        print(f"{n} de {len(muestra)}", flush=True)

with open(os.path.join(AQUI, f"enlace_{argumentos.tarea}.json"), "w") as archivo:
    json.dump({"modelo": MODELO.nombre, "segundos_linkeador": segundos_linkeador, "preguntas": preguntas}, archivo, indent=1)
print("listo", flush=True)
