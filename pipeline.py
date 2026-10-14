"""El pipeline completo: de una query en lenguaje natural a la respuesta de GraphRAG sobre su subgrafo.

Se corre en dos partes:
- 1: por cada consulta se enlazan a las entidades usando entidades/linkear_entidades.py,se arma la seleccion con DIAMOnD k + C3 
y el RWR, y por cada configuracion (solo semillas, mas DIAMOnD, mas C3 y mas RWR) guarda el subgrafo y deja escrito su proyecto 
de GraphRAG.
- 2: indexa cada proyecto y lo consulta en cada modo de busqueda 

Las salidas quedan en resultados/{consulta}/:
- entidades.json: las entidades mismas,  el detalle que tuvo cada enlace y los datos de la llamada al LLM
- {configuracion}/nodos.parquet y aristas.parquet: el subgrafo, con la procedencia de cada nodo como JSON
- {configuracion}/estadisticas.json: nodos y aristas por tipo y por procedencia y los segundos que tardo la seleccion
- {configuracion}/graphrag/: el proyecto de GraphRAG, un respuesta_{modo}.json con la respuesta y sus tiempos de procesamiento

Al final de la parte 2, resultados/resumen.csv junta una fila por consulta, configuracion y modo junto con todas las
consultas de CONSULTAS que ya tengan respuesta

Uso:
  python pipeline.py fase1 [consulta ...]   
  python pipeline.py fase2 [consulta ...]
"""
import argparse
import json
import os
import sys
import time

import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "manipulacion_grafo"))
sys.path.insert(0, os.path.join(AQUI, "expansion"))
sys.path.insert(0, os.path.join(AQUI, "seleccion_subgrafo"))

from entidades.linkear_entidades import Linkeador, linkear_entidades  

from rag.graphrag_msft import (NIVEL_POR_DEFECTO, PARAMETROS_POR_DEFECTO, configuracion_graphrag, 
                               consultar_proyecto, escribir_proyecto, indexar, leer_textos, sufijo_de_nivel,
                               tablas_desde, tokens_del_indice)
from subgrafo_query import (CONFIGURACIONES, K_POR_TIPO, ROL_AGREGADO, SEMILLA_DE_HASH, cargar_grafo, 
                            filtrar_configuracion, materializar_subgrafo, seleccionar)

RESULTADOS = os.path.join(AQUI, "resultados")


#con reportes se responde solo con la busqueda global 
CON_REPORTES = True
MODOS = ("global",) if CON_REPORTES else ("local",)


def procedencias_como_json(procedencias):
    "Las procedencias de un nodo como texto JSON"
    return json.dumps([{"entidad": p.entidad, "paso": p.paso, "rol": p.rol, "iteracion": p.iteracion,
                        "p_valor": p.p_valor, "metodo": p.metodo} for p in procedencias])


def origen_de(procedencias):
    """La capa del pipeline que trajo un nodo.
    Un nodo que alguna entidad fue a buscar cuenta como semilla aunque otro paso tambien lo haya agregado."""
    if any(p.rol != ROL_AGREGADO for p in procedencias):
        return "semilla"
    metodos = {p.metodo for p in procedencias}
    for metodo in ("diamond", "c3", "rwr"):
        if metodo in metodos:
            return metodo


def estadisticas_de(subgrafo):
    """nodos y aristas por tipo y nodos por la capa que los trajo"""
    nodos = subgrafo.nodos
    return {"nodos": len(nodos), "aristas": len(subgrafo.aristas),
            "nodos_por_label": nodos["label"].value_counts().to_dict(),
            "nodos_por_origen": nodos["procedencias"].map(origen_de).value_counts().to_dict(),
            "aristas_por_tipo": subgrafo.aristas["tipo"].value_counts().to_dict()}


def entidades_de(consulta, linkeador):
    """Las entidades dadas o las enlazadas, que luego son guardadas en entidades.json."""
    if consulta.get("entidades"):
        entidades = [tuple(e) for e in consulta["entidades"]]
        return entidades, {"pregunta": consulta["pregunta"], "entidades": entidades, "origen": "dadas"}
    reloj = time.time()
    entidades, enlaces, respuesta = linkear_entidades(consulta["pregunta"], linkeador)
    if not entidades:
        raise ValueError(f"no se enlazo ninguna entidad de la query: {respuesta}")
    detalle = [{"texto": m.texto, "tipo": m.tipo, "nombre_en_ingles": m.nombre_en_ingles, "label": label, "id": id_nodo,
                "paso": paso} for m, label, id_nodo, paso in enlaces]
    return entidades, {"pregunta": consulta["pregunta"], "entidades": entidades, "origen": "enlazadas",
                       "enlaces": detalle, "respuesta_modelo": respuesta, "segundos": round(time.time() - reloj, 2)}


def fase_1_preparar(nombres, consultas, resultados, parametros=PARAMETROS_POR_DEFECTO):
    """Por cada consulta da entidades, hace la  seleccion y el subgrafo y su proyecto de GraphRAG por cada configuraicon"""
    G = cargar_grafo(verbose=False)
    linkeador = None
    #los textos de PrimeKG por nodo entran a las tablas de GraphRAG solo si la corrida lo pide
    textos = leer_textos() if parametros.get("con_texto") else None
    for nombre in nombres:
        consulta = consultas[nombre]
        carpeta = os.path.join(resultados, nombre)
        listos = [os.path.exists(os.path.join(carpeta, c, "graphrag", "output", "entities.parquet"))
                  for c in CONFIGURACIONES]
        if all(listos):
            continue
        os.makedirs(carpeta, exist_ok=True)
        #los diccionarios del enlace se arman solo si alguna consulta necesita enlazar entidades
        if not consulta.get("entidades") and linkeador is None:
            linkeador = Linkeador()
        entidades, registro = entidades_de(consulta, linkeador)
        with open(os.path.join(carpeta, "entidades.json"), "w") as archivo:
            json.dump(registro, archivo, indent=1, ensure_ascii=False)

        #una sola seleccion para las cuatro configuraciones, en su inicio comparten semillas y agregados
        reloj = time.time()
        seleccion = seleccionar(G, entidades, k_por_tipo=K_POR_TIPO)
        segundos_seleccion = round(time.time() - reloj, 1)

        for configuracion in CONFIGURACIONES:
            destino = os.path.join(carpeta, configuracion)
            os.makedirs(destino, exist_ok=True)
            subgrafo = materializar_subgrafo(G, filtrar_configuracion(seleccion, configuracion))
            estadisticas = {**estadisticas_de(subgrafo), "segundos_seleccion": segundos_seleccion}
            nodos = subgrafo.nodos.copy()
            nodos["procedencias"] = nodos["procedencias"].map(procedencias_como_json)
            nodos.to_parquet(os.path.join(destino, "nodos.parquet"), index=False)
            aristas = subgrafo.aristas.copy()
            aristas["propiedades"] = aristas["propiedades"].map(json.dumps)
            aristas.to_parquet(os.path.join(destino, "aristas.parquet"), index=False)
            with open(os.path.join(destino, "estadisticas.json"), "w") as archivo:
                json.dump(estadisticas, archivo, indent=1)
            entities, relationships, text_units = tablas_desde(subgrafo.nodos, subgrafo.aristas, textos)
            escribir_proyecto(os.path.join(destino, "graphrag"), entities, relationships, text_units,
                              configuracion_graphrag(con_reportes=CON_REPORTES, parametros=parametros),
                              reportes_vacios=not CON_REPORTES)
            print(f"[{nombre} {configuracion}] {estadisticas['nodos']} nodos, {estadisticas['aristas']} aristas",
                  flush=True)


def indexar_y_responder(nombres, consultas, resultados, nivel=NIVEL_POR_DEFECTO):
    """Por cada consulta y configuracion indexa el proyecto  y también lo consulta en cada modo. Luego devuelve cuantos 
    indices y respuestas quedaron con error"""
    fallas = 0
    for nombre in nombres:
        pregunta = consultas[nombre]["pregunta"]
        for configuracion in CONFIGURACIONES:
            destino = os.path.join(resultados, nombre, configuracion)
            raiz = os.path.join(destino, "graphrag")
            if not os.path.exists(os.path.join(raiz, "output", "entities.parquet")):
                print(f"[{nombre} {configuracion}] falta la fase 1", flush=True)
                continue
            ruta_indice = os.path.join(destino, "indice.json")
            indice = None
            if os.path.exists(ruta_indice):
                with open(ruta_indice) as archivo:
                    indice = json.load(archivo)
            #un indice que fallo se vuelve a intentar en la corrida siguiente
            if indice is None or indice["codigo"] != 0:
                codigo, segundos, cola = indexar(raiz)
                indice = {"codigo": codigo, "segundos": segundos, "salida": cola}
                with open(ruta_indice, "w") as archivo:
                    json.dump(indice, archivo, indent=1)
                print(f"[{nombre} {configuracion}] indice en {segundos:.0f} s, codigo {codigo}", flush=True)
            if indice["codigo"] != 0:
                fallas += 1
                continue
            for modo in MODOS:
                ruta = os.path.join(raiz, f"respuesta_{modo}{sufijo_de_nivel(nivel)}.json")
                respuesta = None
                if os.path.exists(ruta):
                    with open(ruta) as archivo:
                        respuesta = json.load(archivo)
                #una respuesta que fallo (por ejemplo por desconexion) se vuelve a pedir
                if respuesta is None or respuesta["codigo"] != 0:
                    resultado = consultar_proyecto(raiz, pregunta, ruta, modo, nivel)
                    print(f"[{nombre} {configuracion} {modo}] codigo {resultado['codigo']} en "
                          f"{resultado['segundos']:.0f} s", flush=True)
                    fallas += resultado["codigo"] != 0
    return fallas


def escribir_resumen(consultas, resultados, nivel=NIVEL_POR_DEFECTO):
    """ escribe resultados/resumen.csv, dejando  una fila por consulta"""
    filas = []
    for nombre in consultas:
        for configuracion in CONFIGURACIONES:
            destino = os.path.join(resultados, nombre, configuracion)
            raiz = os.path.join(destino, "graphrag")
            ruta_indice = os.path.join(destino, "indice.json")
            if not os.path.exists(ruta_indice):
                continue
            with open(ruta_indice) as archivo:
                indice = json.load(archivo)
            with open(os.path.join(destino, "estadisticas.json")) as archivo:
                estadisticas = json.load(archivo)
            reportes = os.path.join(raiz, "output", "community_reports.parquet")
            comunidades = len(pd.read_parquet(reportes)) if os.path.exists(reportes) else 0
            for modo in MODOS:
                ruta = os.path.join(raiz, f"respuesta_{modo}{sufijo_de_nivel(nivel)}.json")
                if not os.path.exists(ruta):
                    continue
                with open(ruta) as archivo:
                    resultado = json.load(archivo)
                #las llamadas y los tokens los deja consultar.py junto con el contexto
                ruta_contexto = os.path.join(raiz, f"contexto_{modo}{sufijo_de_nivel(nivel)}.json")
                contexto = {}
                if os.path.exists(ruta_contexto):
                    with open(ruta_contexto) as archivo:
                        contexto = json.load(archivo)
                filas.append({"consulta": nombre, "configuracion": configuracion, "modo": modo,
                              "nodos": estadisticas["nodos"], "aristas": estadisticas["aristas"],
                              "reportes": comunidades, "segundos_seleccion": estadisticas.get("segundos_seleccion"),
                              "segundos_indice": indice["segundos"], **tokens_del_indice(raiz),
                              "segundos_respuesta": resultado["segundos"], "codigo": resultado["codigo"],
                              "llamadas": contexto.get("llamadas"), "tokens_entrada": contexto.get("tokens_entrada"),
                              "tokens_salida": contexto.get("tokens_salida"),
                              "respuesta": resultado["respuesta"]})
    if filas:
        pd.DataFrame(filas).to_csv(os.path.join(resultados, f"resumen{sufijo_de_nivel(nivel)}.csv"), index=False)


def fase_2_responder(nombres, consultas, resultados):
    """Indexa y consulta lo que falte de las consultas pedidas y rearma el resumen con todo lo que haya.
    tambien deevuelve cuantas cosas quedaron con error."""
    fallas = indexar_y_responder(nombres, consultas, resultados)
    escribir_resumen(consultas, resultados)
    return fallas


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fase", choices=("fase1", "fase2"))
    parser.add_argument("nombres", nargs="*", help="consultas a correr; sin ninguna, todas")
    parser.add_argument("--consultas", required=True, help="JSON con las consultas (pregunta y entidades por nombre) en lugar de "
	"CONSULTAS, por ejemplo consultas_bioasq.json")
    parser.add_argument("--resultados", default=RESULTADOS, help="carpeta de resultados (por defecto resultados/)")
    argumentos = parser.parse_args()
    #la semilla de hash se lee al arrancar el interprete, asi que fijarla es volver a lanzarse. Sin ella DIAMOnD
    #desempata por el orden de un set y la seleccion cambia de una corrida a otra
    if os.environ.get("PYTHONHASHSEED") != SEMILLA_DE_HASH:
        os.execve(sys.executable, [sys.executable] + sys.argv, {**os.environ, "PYTHONHASHSEED": SEMILLA_DE_HASH})
    with open(argumentos.consultas) as archivo:
        consultas = json.load(archivo)
    nombres = argumentos.nombres or list(consultas)
    if argumentos.fase == "fase1":
        fase_1_preparar(nombres, consultas, argumentos.resultados)
    else:
        #codigo de salida distinto de cero si algo quedo con error
        sys.exit(1 if fase_2_responder(nombres, consultas, argumentos.resultados) else 0)


if __name__ == "__main__":
    main()
