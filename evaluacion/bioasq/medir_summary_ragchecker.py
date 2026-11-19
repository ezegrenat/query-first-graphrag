 
import argparse
import json
import os
import time

import refchecker.checker.llm_checker as llm_checker
import refchecker.extractor.llm_extractor as llm_extractor
from ragchecker import RAGChecker, RAGResult, RAGResults  #juez, ficha y lista de fichas
from ragchecker.container import RetrievedDoc  #envolver un reporte como documento recuperado
from ragchecker.metrics import all_metrics, recall

from comun import carpeta_de, muestra_de, respuestas_de

CARPETA = carpeta_de("summary")  #aca se guarda todo
RUTA = os.path.join(CARPETA, "ragchecker.json")
RUTA_AFIRMACIONES = os.path.join(CARPETA, "afirmaciones_ideales.json")
OLLAMA = "http://localhost:11500/v1"
LOTE = 8
#gpt-oss razona antes de contestar y el razonamiento cuenta dentro del tope de tokens de la respuesta. RefChecker pide 1000
#para la extraccion y 150 para el chequeo (fijo en llm_checker.py): gpt-oss los gasta razonando y la respuesta llega vacia
#(la extraccion de la ideal de acute_pancreatitis usa ~1400). se sube el tope de todas las llamadas a TOPE
TOPE = 6000


def con_tope(funcion):
    def llamar(*args, max_new_tokens=TOPE, **kwargs):
        return funcion(*args, max_new_tokens=max(max_new_tokens, TOPE), **kwargs)
    return llamar


llm_checker.get_model_batch_response = con_tope(llm_checker.get_model_batch_response)
llm_extractor.get_model_batch_response = con_tope(llm_extractor.get_model_batch_response)


def contexto_de(rep, consulta, configuracion):
    "los reportes de comunidad que vio el map  como documentos recuperados"
    ruta = os.path.join(CARPETA, "respuestas", f"rep{rep}", consulta, configuracion, "contexto_global_nivel0.json")
    with open(ruta) as archivo:
        reportes = json.load(archivo)["tablas"]["reports"]
    return [RetrievedDoc(doc_id=str(reporte["id"]), text=reporte["content"]) for reporte in reportes]


def afirmaciones_de(juez, afirmaciones, consulta, pregunta):
    "las afirmaciones de la primera respuesta ideal"
    if consulta not in afirmaciones:
        item = RAGResult(query_id=consulta, query=pregunta["pregunta"], gt_answer=pregunta["ideal_answer"][0], response="")
        juez.extract_claims([item], extract_type="gt_answer")
        if not item.gt_answer_claims:
            raise RuntimeError(f"{consulta}: el juez no extrajo ninguna afirmacion de la ideal")
        afirmaciones[consulta] = item.gt_answer_claims
        with open(RUTA_AFIRMACIONES, "w") as archivo:
            json.dump(afirmaciones, archivo, indent=1)
    return afirmaciones[consulta]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--consultas", help="nombres separados por coma; si falta, las primeras --muestra o toda la muestra")
    parser.add_argument("--muestra", type=int)
    parser.add_argument("--rep", default="1,2,3")
    parser.add_argument("--modelo", default="gpt-oss:20b")
    parser.add_argument("--con-contexto", action="store_true")
    args = parser.parse_args()
    muestra = muestra_de("summary")
    consultas = args.consultas.split(",") if args.consultas else sorted(muestra)[:args.muestra]
    reps = [int(rep) for rep in args.rep.split(",")]
    respuestas = respuestas_de(muestra)
    respuestas = respuestas[respuestas.rep.isin(reps)]
    hechas = json.load(open(RUTA))["results"] if os.path.exists(RUTA) else []
    listas = {r["query_id"] for r in hechas}
    afirmaciones = json.load(open(RUTA_AFIRMACIONES)) if os.path.exists(RUTA_AFIRMACIONES) else {}
    juez = RAGChecker(extractor_name=f"openai/{args.modelo}", checker_name=f"openai/{args.modelo}",
                      extractor_api_base=OLLAMA, checker_api_base=OLLAMA, openai_api_key="ollama",
                      batch_size_extractor=LOTE, batch_size_checker=LOTE)
    inicio = time.time()
    for numero, consulta in enumerate(consultas, 1):
        con_contexto, sin_contexto = [], []
        for r in respuestas[respuestas.consulta == consulta].itertuples():
            clave = f"rep{r.rep}/{consulta}/{r.configuracion}"
            if clave in listas:
                continue
            item = RAGResult(query_id=clave, query=muestra[consulta]["pregunta"], response=r.respuesta,
                             gt_answer=muestra[consulta]["ideal_answer"][0], retrieved_context=[],
                             gt_answer_claims=afirmaciones_de(juez, afirmaciones, consulta, muestra[consulta]))
            if args.con_contexto and r.configuracion != "sin_grafo":
                item.retrieved_context = contexto_de(r.rep, consulta, r.configuracion)
                con_contexto.append(item)
            else:
                sin_contexto.append(item)
        if con_contexto:
            juez.evaluate(RAGResults(results=con_contexto), all_metrics)
        if sin_contexto:
            juez.evaluate(RAGResults(results=sin_contexto), [recall])
        hechas += [item.to_dict() for item in con_contexto + sin_contexto]
        with open(RUTA, "w") as archivo:
            json.dump({"results": hechas}, archivo, indent=1)
        print(f"{numero} de {len(consultas)}: {consulta}, {len(con_contexto) + len(sin_contexto)} respuestas, "
              f"{(time.time() - inicio) / 60:.1f} minutos en total", flush=True)
