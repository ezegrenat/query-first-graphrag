"""#el paso 1 de linkear_entidades""" 
#  python extraer_menciones.py [--limite 20]
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..", "..", "graphrag"))
from entidades.linkear_entidades import MODELO, PROMPT  
from rag.llm import generar  

BIOASQ = os.path.join(AQUI, "..", "..", "preguntas", "BioASQ-training14b", "training14b.json")
TIPOS_DE_PREGUNTA = ["factoid", "list", "yesno", "summary"]
SALIDA = os.path.join(AQUI, "extracciones.jsonl")

parser = argparse.ArgumentParser()
parser.add_argument("--limite", type=int, default=None, help="solo las primeras n preguntas, para probar")
argumentos = parser.parse_args()

with open(PROMPT) as archivo:
    plantilla = archivo.read()
with open(BIOASQ) as archivo:
    todas = json.load(archivo)["questions"]
preguntas = [pregunta for pregunta in todas if pregunta["type"] in TIPOS_DE_PREGUNTA]
if argumentos.limite:
    preguntas = preguntas[:argumentos.limite]

hechas = set()
if os.path.exists(SALIDA):
    with open(SALIDA) as archivo:
        hechas = {json.loads(linea)["id_bioasq"] for linea in archivo}
pendientes = [pregunta for pregunta in preguntas if pregunta["id"] not in hechas]
print(f"{len(pendientes)} preguntas pendientes de {len(preguntas)}", flush=True)


def extraer(pregunta):
    #el prompt tiene llaves de JSON en los ejemplos, por eso se reemplaza en lugar de usar format
    prompt = plantilla.replace("{pregunta}", pregunta["body"])
    for intento in range(3):
        try:
            texto, datos = generar(MODELO, prompt, formato_json=True)
            return {"id_bioasq": pregunta["id"], "tipo": pregunta["type"], "respuesta": texto,
                    "tokens_entrada": datos.get("tokens_entrada"), "tokens_salida": datos.get("tokens_salida"),
                    "segundos": datos.get("segundos")}
        except Exception as error:
            print(f"{pregunta['id']}: intento {intento + 1} fallo ({error})", flush=True)
            time.sleep(10)
    return None


with open(SALIDA, "a") as salida, ThreadPoolExecutor(max_workers=4) as hilos:
    for n, resultado in enumerate(hilos.map(extraer, pendientes), start=1):
        if resultado is None:
            continue
        salida.write(json.dumps(resultado, ensure_ascii=False) + "\n")
        salida.flush()
        if n % 200 == 0:
            print(f"{n} de {len(pendientes)}", flush=True)
print("listo", flush=True)
