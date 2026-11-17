""" modelos de lenguaje del pipeline.

Hay un modelo por etapa (MODELOS): extraer las menciones de la query, los embeddings de los nombres del grafo, y el que usa GraphRAG para los reportes de comunidad y para responder. Todos son de Ollama: los dos primeros corren en la laptop y los de GraphRAG en una GPU de 24 GB (OLLAMA_GPU). 

Ollama se llama por con temperatura 0 y seed 42 para que la misma entrada de la misma salida. 
"""
import json
import time
import urllib.request
from dataclasses import dataclass

import numpy as np

SEED = 42


@dataclass(frozen=True)
class Modelo:


    proveedor: str
    nombre: str
    url: str


OLLAMA = "http://localhost:11434"

OLLAMA_GPU = "http://localhost:11500"

MODELOS = {
    "extraccion": Modelo("ollama", "qwen2.5:3b", OLLAMA),
    "embeddings": Modelo("ollama", "nomic-embed-text", OLLAMA),
    "graphrag": Modelo("ollama", "qwen3:30b-a3b-instruct-2507-q4_K_M", OLLAMA_GPU),
    "graphrag_embeddings": Modelo("ollama", "nomic-embed-text", OLLAMA_GPU),
}


def pedir(url, cuerpo):
    pedido = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), headers={"Content-Type": "application/json"})
    #en CPU una generacion larga puede tardar minutos
    with urllib.request.urlopen(pedido, timeout=1800) as respuesta:
        return json.loads(respuesta.read())


def generar(modelo, prompt, formato_json=False, max_tokens=None, temperatura=0, seed=SEED):
    if modelo.proveedor != "ollama":
        raise ValueError(f"el proveedor {modelo.proveedor!r} todavia no esta implementado")
    cuerpo = {"model": modelo.nombre, "prompt": prompt, "stream": False,
              "options": {"temperature": temperatura, "seed": seed}}
    #con format json Ollama restringe la salida a un JSON valido
    if formato_json:
        cuerpo["format"] = "json"
    #num_predict es el tope de tokens de salida de Ollama
    if max_tokens is not None:
        cuerpo["options"]["num_predict"] = max_tokens
    reloj = time.time()
    datos = pedir(f"{modelo.url}/api/generate", cuerpo)
    return datos["response"], {"tokens_entrada": datos.get("prompt_eval_count"),
                               "tokens_salida": datos.get("eval_count"),
                               "segundos": round(time.time() - reloj, 2)}


def embeber(modelo, textos, de_a=256):
    if modelo.proveedor != "ollama":
        raise ValueError(f"el proveedor {modelo.proveedor!r} todavia no esta implementado")
    filas = []
    for inicio in range(0, len(textos), de_a):
        datos = pedir(f"{modelo.url}/api/embed", {"model": modelo.nombre, "input": textos[inicio:inicio + de_a]})
        filas.extend(datos["embeddings"])
    return np.array(filas, dtype=np.float32)
