"""Consulta un proyecto de GraphRAG ya indexado por su API y guarda el contexto que recibio el modelo.

El CLI de graphrag query imprime solo la respuesta. Aca se arma el mismo motor de busqueda que arma la API, pero se
llama a search en vez de stream_search, porque devuelve ademas el contexto, las llamadas al modelo y los tokens.
Corre con el python del entorno de GraphRAG, no con el del pipeline: graphrag_msft.consultar_proyecto lo lanza como
subproceso.

Esto es una adaptacion de dohttps://github.com/microsoft/graphrag/tree/v3.2.0 archivos de GraphRAG 3.2.0 (, en
packages/graphrag/graphrag/):
- api/query.py: motor_local reproduce local_search_streaming y motor_global reproduce global_search_streaming, que
  arman el motor con get_local_search_engine y get_global_search_engine a partir de las tablas leidas con los
  read_indexer_* y de los prompts del proyecto. Lo que cambia aca: se llama a search y no a stream_search, la busqueda
  local no lee covariates (el indice no extrae claims), la global puede usar otro prompt de reduce
  (prompt_de_reduce) y prende allow_general_knowledge con --memoria.

- cli/query.py: main reproduce run_local_search y run_global_search (cargar el settings.yaml con load_config y las
  tablas de output/) y leer_tablas reproduce _resolve_output_files. Los valores por defecto son los de
  graphrag query en cli/main.py: nivel de comunidad 2 y sin seleccion dinamica de comunidades.

Uso: python consultar.py RAIZ local|global PREGUNTA RUTA_CONTEXTO [SEED TEMPERATURA] [--nivel N]
     [--formato FORMATO] [--tipo-respuesta TEXTO] [--reduce ARCHIVO] [--memoria]
Con SEED y TEMPERATURA pisa los del modelo de respuestas del settings.yaml, para repetir una consulta cambiando
solo eso. Imprime la respuesta por salida estandar, como el CLI, y deja en RUTA_CONTEXTO un JSON con:
- tablas: el contexto como registros, una lista por tabla (entities, relationships, reports y sources en la
  busqueda local, reports en la global);
- texto: el contexto tal como entro en el prompt (en la global, un texto por lote del map);
- map (solo global): por cada lote, la respuesta del map y sus tokens, y el contexto que entro al reduce;
- llamadas, tokens_entrada, tokens_salida y segundos de toda la consulta.
"""
import argparse
import asyncio
import json
import os

import pandas as pd
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider

from graphrag.config.embeddings import entity_description_embedding
from graphrag.config.load_config import load_config
from graphrag.data_model.data_reader import DataReader
from graphrag.logger.standard_logging import init_loggers
from graphrag.query.factory import get_global_search_engine, get_local_search_engine
from graphrag.query.indexer_adapters import (read_indexer_communities, read_indexer_entities,
                                             read_indexer_relationships, read_indexer_reports,
                                             read_indexer_text_units)
from graphrag.utils.api import get_embedding_store, load_search_prompt

#corre como script con esta carpeta en sys.path y por eso importa formatos suelto. desde el pipeline es rag.formatos
from formatos import FORMATOS, REDUCE_EXACTO

#los valores por defecto de graphrag query
NIVEL_DE_COMUNIDAD = 2


def leer_tablas(config, nombres):
    """leer las tablas del indice (output/*.parquet) como DataFrames. La API de grpa"""
    
    storage = create_storage(config.output_storage) #donde estan los archivos 
    #el table provider lee cada tabla de output/ en el formato de la configuracion (parquet por defecto) y el
    #DataReader le pasa cada columna al tipo que esperan los read_indexer_*. La lectura ocurre al llamar a sus metodos

    lector = DataReader(create_table_provider(config.table_provider, storage=storage))
    return {nombre: asyncio.run(getattr(lector, nombre)()) for nombre in nombres}


def motor_local(config, nivel, formato, tipo_respuesta=None):
    "Arma la busqueda local de GraphRAG y devuelve un objeto LocalSearch listo"
    tablas = leer_tablas(config, ["communities", "community_reports", "text_units", "relationships", "entities"])
    #convertir esas tablas a objetos de GraphRAG:
    return get_local_search_engine(
        config=config,
        #reportes de comunidades de nivel <= nivel y para cada nodo con su comunidad mas profunda
        reports=read_indexer_reports(tablas["community_reports"], tablas["communities"], nivel), 
        text_units=read_indexer_text_units(tablas["text_units"]), #conversion directa 
        entities=read_indexer_entities(tablas["entities"], tablas["communities"], nivel), #conversion directa 
        relationships=read_indexer_relationships(tablas["relationships"]), #conversion directa 
        covariates={"claims": []}, #afirmaciones que graphrag puede extraer del texto, en nuestro caso quedan vacios 
        description_embedding_store=get_embedding_store(config=config.vector_store,
                                                        embedding_name=entity_description_embedding),
        response_type=tipo_respuesta or FORMATOS[formato],
        system_prompt=load_search_prompt(config.local_search.prompt))


def prompt_de_reduce(config, formato, reduce=None):
    """establece que prompt de sistema usa el paso de reduce en la busqueda global 
    si es exacto_factoid o exacta_list usa reduce_exacto, en cualquier otro caso usa prompts/global_search_reduce_system_prompt.txt"""
    if reduce:
        with open(reduce) as archivo:
            return archivo.read()
    if formato.startswith("exacta"):
        with open(REDUCE_EXACTO) as archivo:
            return archivo.read()
    return load_search_prompt(config.global_search.reduce_prompt)


def motor_global(config, nivel, formato, tipo_respuesta=None, reduce=None, memoria=True):
    "Arma la busqueda global de GraphRAG y devuelve un objeto Global Search listo"
    tablas = leer_tablas(config, ["entities", "communities", "community_reports"])
    motor = get_global_search_engine(
        config,
        reports=read_indexer_reports(tablas["community_reports"], tablas["communities"],
                                     community_level=nivel, dynamic_community_selection=False),
        entities=read_indexer_entities(tablas["entities"], tablas["communities"], community_level=nivel),
        communities=read_indexer_communities(tablas["communities"], tablas["community_reports"]),
        response_type=tipo_respuesta or FORMATOS[formato],
        dynamic_community_selection=False,
        map_system_prompt=load_search_prompt(config.global_search.map_prompt),
        reduce_system_prompt=prompt_de_reduce(config, formato, reduce),
        general_knowledge_inclusion_prompt=load_search_prompt(config.global_search.knowledge_prompt))
    #la factory de GraphRAG lo deja fijo en False y no lo recibe por parametro
    motor.allow_general_knowledge = memoria
    return motor


def como_json(valor):
    "convierte lo que devuelve GraphRAG en algo que json.dump pueda escribir. "
    if isinstance(valor, dict):
        return {nombre: como_json(tabla) for nombre, tabla in valor.items()}
    if isinstance(valor, pd.DataFrame):
        return json.loads(valor.to_json(orient="records"))
    if isinstance(valor, list):
        return [como_json(v) for v in valor]
    return valor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("raiz") 
    parser.add_argument("metodo", choices=("local", "global"))
    parser.add_argument("pregunta")
    parser.add_argument("ruta_contexto")
    parser.add_argument("seed", nargs="?", type=int)
    parser.add_argument("temperatura", nargs="?", type=float)
    parser.add_argument("--nivel", type=int, default=NIVEL_DE_COMUNIDAD)
    parser.add_argument("--formato", choices=FORMATOS, default="prosa")
    #un formato y un prompt de reduce propios que pisan los de --formato
    parser.add_argument("--tipo-respuesta", default=None, help="el texto de response_type")
    parser.add_argument("--reduce", default=None, help="un archivo con el prompt de reduce de la busqueda global")
    parser.add_argument("--memoria", action="store_true",
                        help="prende allow_general_knowledge: el reduce puede sumar conocimiento propio del modelo, marcado")
    argumentos = parser.parse_args()
    metodo, pregunta = argumentos.metodo, argumentos.pregunta
    #GraphRAG resuelve rutas relativas desde la raiz del proyecto, asi que la salida se fija antes como absoluta
    ruta_contexto = os.path.abspath(argumentos.ruta_contexto)
    config = load_config(root_dir=os.path.abspath(argumentos.raiz))
    if argumentos.temperatura is not None:
        respuestas = config.completion_models["respuestas_completion_model"].call_args
        respuestas["seed"] = argumentos.seed
        respuestas["temperature"] = argumentos.temperatura
    init_loggers(config=config, verbose=False, filename="query.log")
    if metodo == "local":
        motor = motor_local(config, argumentos.nivel, argumentos.formato, argumentos.tipo_respuesta)
    else:
        motor = motor_global(config, argumentos.nivel, argumentos.formato, argumentos.tipo_respuesta,
                             argumentos.reduce, argumentos.memoria)
    resultado = asyncio.run(motor.search(pregunta))

    contexto = {"metodo": metodo, "pregunta": pregunta, "formato": argumentos.formato,
                "modelo": config.completion_models["respuestas_completion_model"].call_args,
                "tablas": como_json(resultado.context_data), "texto": como_json(resultado.context_text),
                "llamadas": resultado.llm_calls,
                "tokens_entrada": resultado.prompt_tokens, "tokens_salida": resultado.output_tokens,
                "segundos": round(resultado.completion_time, 1)}
    if metodo == "global":
        contexto["map"] = [{"respuesta": como_json(r.response), "contexto": como_json(r.context_text),
                            "tokens_entrada": r.prompt_tokens, "tokens_salida": r.output_tokens}
                           for r in resultado.map_responses]
        contexto["contexto_reduce"] = como_json(resultado.reduce_context_text)
        contexto["memoria_permitida"] = argumentos.memoria
    with open(ruta_contexto, "w") as archivo:
        json.dump(contexto, archivo, indent=1, ensure_ascii=False)

    respuesta = resultado.response
    print(respuesta if isinstance(respuesta, str) else json.dumps(respuesta, ensure_ascii=False))


if __name__ == "__main__":
    main()
