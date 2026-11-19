"""modelos de lenguaje del pipeline.

MODELOS tiene el que usa GraphRAG para los reportes de comunidad y para responder, y el de sus embeddings. El que detecta las menciones de la query esta en entidades/linkear_entidades.py. Todos son de Ollama y corren en una GPU de 24 GB (OLLAMA_GPU), que es el Ollama de esa maquina o un tunel a ella en el puerto 11500.

Ollama se llama con temperatura 0 y seed 42 para que la misma entrada de la misma salida.
"""
import json
import time
import urllib.request
from dataclasses import dataclass

SEED = 42


@dataclass(frozen=True)
class Modelo:
    proveedor: str
    nombre: str
    url: str


OLLAMA_GPU = "http://localhost:11500"

MODELOS = {
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

