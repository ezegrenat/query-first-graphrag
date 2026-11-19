"""indexar con graphrag index los proyectos que deja seleccionar.py y que reusar_indices.py no reuso, en el orden de claves.json"""
#necesita el Ollama de la GPU (OLLAMA_GPU en graphrag/rag/llm.py):
#python indexar.py --tarea summary
#termina con codigo 1 si quedo algun indice con error
import json
import os
import shutil
import sys

from comun import SELECCION, argumentos, carpeta_de, cargar_env, claves_de

cargar_env()
from rag.graphrag_msft import indexar, tokens_del_log  # noqa: E402

tarea = argumentos().tarea
pendientes = list(dict.fromkeys(claves_de(tarea).values()))

errores = 0
for n, clave in enumerate(pendientes, start=1):
    for configuracion in SELECCION:
        carpeta = os.path.join(carpeta_de(tarea), "indices", clave, configuracion)
        ruta_indice = os.path.join(carpeta, "indice.json")
        if os.path.exists(ruta_indice):
            with open(ruta_indice) as archivo:
                indice = json.load(archivo)
            if indice["codigo"] == 0 or indice.get("vacio"):
                continue
        with open(os.path.join(carpeta, "estadisticas.json")) as archivo:
            if json.load(archivo)["aristas"] == 0:
                with open(ruta_indice, "w") as salida:
                    json.dump({"codigo": None, "vacio": True}, salida, indent=1)
                continue
        proyecto = os.path.join(carpeta, "graphrag")
        codigo, segundos, cola = indexar(proyecto)
        indice = {"codigo": codigo, "segundos": segundos, "salida": cola}
        if codigo == 0:
            indice.update(tokens_del_log(proyecto) or {})
        with open(ruta_indice, "w") as archivo:
            json.dump(indice, archivo, indent=1)
        if codigo == 0:
            shutil.rmtree(os.path.join(proyecto, "cache"), ignore_errors=True)
        else:
            errores += 1
        print(f"[{n} de {len(pendientes)}] {clave} {configuracion}: codigo {codigo} en {segundos:.0f} s", flush=True)

print(f"{len(pendientes)} conjuntos, {errores} indices con error", flush=True)
sys.exit(1 if errores else 0)
