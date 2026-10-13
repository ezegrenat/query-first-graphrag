"""Un subgrafo dentro de Microsoft GraphRAG, con "Bring Your Own Graph".

GraphRAG normalmente extrae el grafo de un texto con el LLM. Aca se le da el grafo ya armado, como las
tablas que produciria esa extraccion (https://microsoft.github.io/graphrag/index/byog/):
- entities: un nodo por fila. title es el nombre (GraphRAG une relaciones y entidades por title), type el
  label y description el tipo y el nombre.
- relationships: una arista por fila, con source y target por title y como description la frase de
  verbalizar.py.
- text_units: uno por entidad, con las frases de todas sus aristas. Es el texto que la busqueda local
  puede poner en el contexto.
Con eso GraphRAG solo corre create_communities, create_community_reports y generate_text_embeddings.

Los modelos salen de llm.MODELOS ("graphrag" para los reportes y las respuestas, "graphrag_embeddings" para
los embeddings), por el endpoint compatible con OpenAI de Ollama en la GPU de pandora, de a cuatro pedidos a la
vez. El ejecutable de GraphRAG es el del entorno que indique GRAPHRAG_BIN.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

import pandas as pd

from rag.llm import MODELOS, SEED
from rag.verbalizar import frase

AQUI = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(AQUI, "plantilla")
#GraphRAG vive en su propio entorno, con dependencias que no conviven con las del resto del pipeline. Es GraphRAG
#3.2.0 con el contexto de los reportes de comunidad armado con todas las aristas de cada nodo (ver
#requirements_graphrag.txt). GRAPHRAG_BIN apunta al ejecutable de ese entorno
GRAPHRAG = os.environ.get("GRAPHRAG_BIN", "graphrag")
MODOS_DE_BUSQUEDA = ("local", "global")
#el python del entorno de GraphRAG, para el script que consulta por la API y guarda el contexto
PYTHON_GRAPHRAG = os.path.join(os.path.dirname(GRAPHRAG), "python")
CONSULTAR = os.path.join(AQUI, "consultar.py")
#el nivel de comunidad de graphrag query. lo respondido con otro nivel lleva el nivel en el nombre del archivo
NIVEL_POR_DEFECTO = 2
#tope de tokens de salida por llamada: uno para los reportes de comunidad y otro, mas corto, para las respuestas
MAX_TOKENS_REPORTES = 2500
MAX_TOKENS_RESPUESTAS = 2000
#los valores  que mas pesan en el tiempo del indice y de la busqueda global. los largos son palabras pedidas en el prompt. tamano_comunidad es 
# el tamano maximo de una comunidad antes de que Leiden la parta y contexto_map los tokens de cada lote de reportes del paso map

PARAMETROS_POR_DEFECTO = {"largo_reportes": 1000, "largo_map": 1000, "largo_respuesta": 1000, "contexto_map": 2500,
                          "tamano_comunidad": 10, "con_texto": False}
#los textos de PrimeKG por nodo (la definicion de cada enfermedad y la descripcion de DrugBank de cada droga), que
#escribe grafos/primekg_integrado/textos_nodos.py. Con con_texto, tablas_desde los pone en el text unit y en la
#descripcion de cada entidad
ARCHIVO_TEXTOS = os.path.join(AQUI, "..", "grafos", "primekg_integrado", "datos", "textos_nodos.parquet")
#tope de palabras del texto de un nodo, cortando en la ultima oracion completa. 
MAX_PALABRAS_TEXTO = 150


def nombre_de_corrida(parametros):
    "crea nombre para la carpeta que guardará los resultados de la corrida"
    return (f"reportes{parametros['largo_reportes']}_map{parametros['largo_map']}_"
            f"respuesta{parametros['largo_respuesta']}_lotes{parametros['contexto_map']}_"
            f"comunidades{parametros['tamano_comunidad']}" + ("_texto" if parametros.get("con_texto") else ""))


def leer_textos():
    "lee el ARCHIVO_TEXTOS que es textos_nodos.parquet y retorna {(label,id) : texto}. Si el parquet no existe retorna un dict vacio"
    if not os.path.exists(ARCHIVO_TEXTOS):
        return {}
    textos = pd.read_parquet(ARCHIVO_TEXTOS, columns=["label", "id", "texto"])
    return dict(zip(zip(textos["label"], textos["id"]), textos["texto"]))


def oraciones_de(texto):
    "dado un texto lo retorna partido en oraciones"
    return re.split(r"(?<=[.!?])\s+(?=[A-Z])", texto.strip())


def recortar_texto(texto, max_palabras=MAX_PALABRAS_TEXTO):
    "El texto hasta max_palabras, cortado en la ultima oracion completa. Si la primera oracion sola se pasa se lo corta por palabras"
    oraciones, palabras = [], 0
    for oracion in oraciones_de(texto):
        if palabras + len(oracion.split()) > max_palabras:
            break
        oraciones.append(oracion)
        palabras += len(oracion.split())
    if not oraciones:
        return " ".join(texto.split()[:max_palabras])
    return " ".join(oraciones)

#plantilla de configuracion dada por graphrag con campos a completar 

PLANTILLA_CONFIGURACION = """completion_models:
  default_completion_model:
    model_provider: openai
    model: {modelo}
    api_base: {api_base}/v1
    auth_method: api_key
    api_key: ollama
    call_args:
      temperature: 0
      seed: {seed}
      max_tokens: {max_tokens_reportes}
    retry:
      type: exponential_backoff
      max_retries: 2
      base_delay: 2
  respuestas_completion_model:
    model_provider: openai
    model: {modelo}
    api_base: {api_base}/v1
    auth_method: api_key
    api_key: ollama
    call_args:
      temperature: 0
      seed: {seed}
      max_tokens: {max_tokens_respuestas}
    retry:
      type: exponential_backoff
      max_retries: 2
      base_delay: 2

embedding_models:
  default_embedding_model:
    model_provider: openai
    model: {modelo_embeddings}
    api_base: {api_base_embeddings}/v1
    auth_method: api_key
    api_key: ollama
    retry:
      type: exponential_backoff
      max_retries: 2
      base_delay: 2

concurrent_requests: 4

workflows: [create_communities, create_community_reports, generate_text_embeddings]

input_storage:
  type: file
  base_dir: "input"

output_storage:
  type: file
  base_dir: "output"

reporting:
  type: file
  base_dir: "logs"

cache:
  type: json
  storage:
    type: file
    base_dir: "cache"

vector_store:
  type: lancedb
  db_uri: output/lancedb

embed_text:
  embedding_model_id: default_embedding_model

cluster_graph:
  max_cluster_size: {tamano_comunidad}

community_reports:
  completion_model_id: default_completion_model
  graph_prompt: "prompts/community_report_graph.txt"
  text_prompt: "prompts/community_report_text.txt"
  max_length: {largo_reportes}
  max_input_length: 2500

local_search:
  completion_model_id: respuestas_completion_model
  embedding_model_id: default_embedding_model
  prompt: "prompts/local_search_system_prompt.txt"
  max_context_tokens: 2500

global_search:
  completion_model_id: respuestas_completion_model
  map_prompt: "prompts/global_search_map_system_prompt.txt"
  reduce_prompt: "prompts/global_search_reduce_system_prompt.txt"
  knowledge_prompt: "prompts/global_search_knowledge_system_prompt.txt"
  max_context_tokens: {contexto_map}
  data_max_tokens: 5000
  map_max_length: {largo_map}
  reduce_max_length: {largo_respuesta}
"""


#las columnas de la tabla de reportes de comunidad de GraphRAG (graphrag/data_model/schemas.py). Un proyecto sin
#reportes necesita la tabla igual, vacia, porque la busqueda local la lee
COLUMNAS_REPORTES = ["id", "human_readable_id", "community", "level", "parent", "children", "title", "summary",
                     "full_content", "rank", "rating_explanation", "findings", "full_content_json", "period", "size"]


def configuracion_graphrag(modelo=MODELOS["graphrag"], modelo_embeddings=MODELOS["graphrag_embeddings"],
                           con_reportes=True, parametros=PARAMETROS_POR_DEFECTO):
    """Toma la plantilla que espera graphRAG y llena los valores a completar. 
    """
    configuracion = PLANTILLA_CONFIGURACION.format(modelo=modelo.nombre, api_base=modelo.url, seed=SEED,
                                                   max_tokens_reportes=MAX_TOKENS_REPORTES,
                                                   max_tokens_respuestas=MAX_TOKENS_RESPUESTAS,
                                                   modelo_embeddings=modelo_embeddings.nombre,
                                                   api_base_embeddings=modelo_embeddings.url,
                                                   largo_reportes=parametros["largo_reportes"],
                                                   largo_map=parametros["largo_map"],
                                                   largo_respuesta=parametros["largo_respuesta"],
                                                   contexto_map=parametros["contexto_map"],
                                                   tamano_comunidad=parametros["tamano_comunidad"])
    if con_reportes:
        return configuracion
    return (configuracion
            .replace("workflows: [create_communities, create_community_reports, generate_text_embeddings]",
                     "workflows: [create_communities, generate_text_embeddings]")
            .replace("embed_text:\n  embedding_model_id: default_embedding_model",
                     "embed_text:\n  embedding_model_id: default_embedding_model\n  names: [entity_description]")
            .replace("  max_context_tokens: 2500\n\nglobal_search:",
                     "  max_context_tokens: 2500\n  community_prop: 0.0\n\nglobal_search:"))


def tablas_desde(nodos, aristas, textos=None):
    """completa (entities, relationships, text_units) que pide Bring Your Own Graph de GraphRAG a partir de un subgrafo.

    nodos necesita id, nombre y label, y aristas id_a, id_b, label_a, label_b y tipo, que son las columnas
    de materializar_subgrafo. La descripcion de cada entidad es solo su tipo y su nombre: decir de donde vino
    (semilla, agregado por DIAMOnD, por C3 o por el RWR) podria sesgar al LLM."""
    nodos = nodos.reset_index(drop=True)
    aristas = aristas.reset_index(drop=True)
    #textos es {(label, id): texto}, de leer_textos. Con textos, el text unit de un nodo con texto arranca con ese texto
    #recortado a MAX_PALABRAS_TEXTO y siguen las oraciones de sus aristas (el texto va primero porque GraphRAG trunca por
    #el final), y su descripcion suma el mismo texto recortado: "Disease MARFAN SYNDROME. Marfan syndrome is a ...". La
    #descripcion es lo que se embebe y lo que ven los reportes de comunidad (el prompt de reportes recibe la tabla de
    #entidades y la de relaciones, nunca los text units), asi que es la unica forma de que el texto llegue a la busqueda
    #global sin cambiar el workflow de reportes
    textos = textos or {}
    #el title va en mayusculas porque la deteccion de comunidades de GraphRAG
    nombres = nodos["nombre"].str.upper()
    #el title tiene que ser unico: a los nombres repetidos se les agrega el label
    repetidos = set(nombres[nombres.duplicated(keep=False)])
    titulo = {}
    for id_nodo, nombre, label in zip(nodos["id"], nombres, nodos["label"]):
        titulo[id_nodo] = f"{nombre} ({label.upper()})" if nombre in repetidos else nombre
    #si todavia quedan repetidos (dos nodos del mismo label con el mismo nombre, pasa en el grafo entero),
    #el title lleva tambien el id
    titulos = pd.Series(titulo)
    for id_nodo in titulos[titulos.duplicated(keep=False)].index:
        titulo[id_nodo] = f"{titulo[id_nodo]} [{id_nodo}]"

    columnas = zip(aristas["tipo"], aristas["id_a"], aristas["label_a"], aristas["id_b"], aristas["label_b"])
    frases = [frase(tipo, titulo[a], label_a, titulo[b], label_b) for tipo, a, label_a, b, label_b in columnas]
    grado = pd.concat([aristas["id_a"], aristas["id_b"]]).value_counts()

    relationships = pd.DataFrame({
        "id": [f"r{i}" for i in range(len(aristas))],
        "human_readable_id": range(len(aristas)),
        "source": [titulo[i] for i in aristas["id_a"]],
        "target": [titulo[i] for i in aristas["id_b"]],
        "description": frases,
        "weight": 1.0,
        "combined_degree": [int(grado[a] + grado[b]) for a, b in zip(aristas["id_a"], aristas["id_b"])],
        #la frase de la arista esta en el text unit de sus dos extremos
        "text_unit_ids": [[f"t_{a}", f"t_{b}"] for a, b in zip(aristas["id_a"], aristas["id_b"])],
    })

    #para cada nodo, las posiciones de sus aristas en la tabla, contando los dos extremos. Se arma de una vez
    #porque recorrer la tabla nodo por nodo tarda demasiado con el grafo entero
    extremos = pd.concat([pd.DataFrame({"nodo": aristas["id_a"], "arista": aristas.index}),
                          pd.DataFrame({"nodo": aristas["id_b"], "arista": aristas.index})])
    aristas_por_nodo = extremos.sort_values("arista", kind="stable").groupby("nodo")["arista"].apply(list).to_dict()

    #el texto de PrimeKG de cada nodo que lo tiene, ya recortado
    texto_del_nodo = {}
    for id_nodo, label in zip(nodos["id"], nodos["label"]):
        if (label, id_nodo) in textos:
            texto_del_nodo[id_nodo] = recortar_texto(textos[(label, id_nodo)])

    text_units = []
    for id_nodo in nodos["id"]:
        propias = aristas_por_nodo.get(id_nodo, [])
        texto = " ".join(([texto_del_nodo[id_nodo]] if id_nodo in texto_del_nodo else []) + [frases[i] for i in propias])
        text_units.append({
            "id": f"t_{id_nodo}", "human_readable_id": len(text_units), "text": texto,
            "n_tokens": len(texto.split()), "document_id": "subgrafo",
            "entity_ids": [f"e_{id_nodo}"], "relationship_ids": [f"r{i}" for i in propias], "covariate_ids": [],
        })

    descripciones = []
    for id_nodo, label in zip(nodos["id"], nodos["label"]):
        descripcion = f"{label} {titulo[id_nodo]}."
        if id_nodo in texto_del_nodo:
            descripcion += " " + texto_del_nodo[id_nodo]
        descripciones.append(descripcion)
    entities = pd.DataFrame({
        "id": [f"e_{i}" for i in nodos["id"]],
        "human_readable_id": range(len(nodos)),
        "title": [titulo[i] for i in nodos["id"]],
        "type": nodos["label"].str.upper(),
        "description": descripciones,
        "text_unit_ids": [[f"t_{i}"] for i in nodos["id"]],
        "frequency": 1,
        "degree": [int(grado.get(i, 0)) for i in nodos["id"]],
    })
    return entities, relationships, pd.DataFrame(text_units)


def escribir_proyecto(raiz, entities, relationships, text_units, configuracion, reportes_vacios=False):
    """Deja en raiz un proyecto de GraphRAG listo para indexar: su settings.yaml, los prompts de la plantilla y
    las tablas en output/. Con reportes_vacios escribe tambien la tabla de reportes sin filas."""
    os.makedirs(os.path.join(raiz, "output"), exist_ok=True)
    os.makedirs(os.path.join(raiz, "input"), exist_ok=True)
    shutil.copytree(os.path.join(PLANTILLA, "prompts"), os.path.join(raiz, "prompts"), dirs_exist_ok=True)
    with open(os.path.join(raiz, "settings.yaml"), "w") as f:
        f.write(configuracion)
    entities.to_parquet(os.path.join(raiz, "output", "entities.parquet"), index=False)
    relationships.to_parquet(os.path.join(raiz, "output", "relationships.parquet"), index=False)
    text_units.to_parquet(os.path.join(raiz, "output", "text_units.parquet"), index=False)
    if reportes_vacios:
        pd.DataFrame(columns=COLUMNAS_REPORTES).to_parquet(os.path.join(raiz, "output", "community_reports.parquet"),
                                                          index=False)


def indexar(raiz):
    """Corre graphrag index sobre el proyecto. Devuelve (codigo, segundos, final de la salida)."""
    inicio = time.time()
    proceso = subprocess.run([GRAPHRAG, "index", "--root", raiz], capture_output=True, text=True)
    return proceso.returncode, round(time.time() - inicio, 1), (proceso.stdout + proceso.stderr)[-3000:]


def tokens_del_indice(raiz):
    """graphrag guarda en su cache cada llamda al modelo con los tokens que uso. los reportes de comunidad
    quedan en cache/community_reporting, una llamada por archivo"""
    llamadas, tokens_entrada, tokens_salida = 0, 0, 0
    for ruta in glob.glob(os.path.join(raiz, "cache", "community_reporting", "*")):
        with open(ruta) as archivo:
            uso = json.load(archivo)["result"]["response"]["usage"]
        llamadas += 1
        tokens_entrada += uso["prompt_tokens"]
        tokens_salida += uso["completion_tokens"]
    return {"llamadas_indice": llamadas, "tokens_entrada_indice": tokens_entrada,
            "tokens_salida_indice": tokens_salida}


def ya_respondida(ruta):
    """una respuesta que quedo con error por algun motivo se tiene que volver a pedir"""
    if not os.path.exists(ruta):
        return False
    with open(ruta) as archivo:
        return json.load(archivo)["codigo"] == 0


def sufijo_de_nivel(nivel):
    return "" if nivel == NIVEL_POR_DEFECTO else f"_nivel{nivel}"


def consultar_proyecto(raiz, pregunta, ruta_salida, metodo="local", nivel=NIVEL_POR_DEFECTO, formato="prosa",
                       tipo_respuesta=None, reduce=None, memoria=False):
    """corre consultar.py. Se le pasa el metodo (local o global), el nivel de comunidad, un prompt de reduce propio, el formato y un tipo de respuesta 
    (opcional, es para evlauar BioASQ, en caso contrario se usa el predefinido por msft)
    Memoria = True habilita allow_general_knowledge, que permite sumar conocimiento propio al reduce"""
    ruta_contexto = os.path.join(os.path.dirname(ruta_salida), f"contexto_{metodo}{sufijo_de_nivel(nivel)}.json")
    inicio = time.time()
    comando = [PYTHON_GRAPHRAG, CONSULTAR, raiz, metodo, pregunta, ruta_contexto, "--nivel", str(nivel),
               "--formato", formato]
    if tipo_respuesta:
        comando += ["--tipo-respuesta", tipo_respuesta]
    if reduce:
        comando += ["--reduce", reduce]
    if memoria:
        comando += ["--memoria"]
    proceso = subprocess.run(comando, capture_output=True, text=True)
    respuesta = proceso.stdout.strip()
    #graphrag atrapa algunos errores del modelo (por ejemplo un contexto mas largo que la ventana) y devuelve
    #una respuesta vacia con codigo 0. se marca como error para que se vuelva a pedir
    codigo = proceso.returncode if respuesta else (proceso.returncode or 1)
    resultado = {"modelo": f"graphrag {metodo} {MODELOS['graphrag'].nombre}", "pregunta": pregunta, "formato": formato,
                 "respuesta": respuesta, "error": proceso.stderr[-3000:],
                 "codigo": codigo, "segundos": round(time.time() - inicio, 1)}
    with open(ruta_salida, "w") as f:
        json.dump(resultado, f, indent=1, ensure_ascii=False)
    return resultado
