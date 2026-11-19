"""BERTScore de las respuestas de summary contra la mejor de las ideales, con roberta-large reescalado. deja summary/bertscore.csv y saltea lo que ya esta medido"""
#se corre con el entorno de requirements_bertscore.txt
#python medir_bertscore.py
import os

import pandas as pd

from comun import carpeta_de, muestra_de, respuestas_de

CARPETA = carpeta_de("summary")


def ya_medidas(ruta, columnas):
    "las claves que ya estan en un CSV de salida"
    if not os.path.exists(ruta):
        return pd.DataFrame(), set()
    hechas = pd.read_csv(ruta)
    return hechas, set(map(tuple, hechas[columnas].itertuples(index=False)))


def medir_bertscore(respuestas, muestra):
    from bert_score import BERTScorer
    ruta = os.path.join(CARPETA, "bertscore.csv")
    hechas, claves = ya_medidas(ruta, ["rep", "consulta", "configuracion"])
    pendientes = respuestas[[tuple(f) not in claves for f in respuestas[["rep", "consulta", "configuracion"]].itertuples(index=False)]]
    print(f"bertscore: {len(pendientes)} respuestas por medir")
    filas = []
    if len(pendientes):
        puntaje = BERTScorer(model_type="roberta-large", lang="en", rescale_with_baseline=True, device="cuda")
        #cada respuesta contra cada una de sus ideales, y se queda la mejor
        pares = [(i, r.respuesta, ideal) for i, r in enumerate(pendientes.itertuples()) for ideal in muestra[r.consulta]["ideal_answer"]]
        _, _, f1 = puntaje.score([p[1] for p in pares], [p[2] for p in pares], batch_size=32)
        mejor = pd.Series(f1.numpy(), index=[p[0] for p in pares]).groupby(level=0).max()
        for i, r in enumerate(pendientes.itertuples()):
            filas.append({"rep": r.rep, "consulta": r.consulta, "configuracion": r.configuracion, "bertscore": float(mejor[i])})
    pd.concat([hechas, pd.DataFrame(filas)]).to_csv(ruta, index=False)


if __name__ == "__main__":
    muestra = muestra_de("summary")
    respuestas = respuestas_de(muestra)
    print(f"{len(muestra)} preguntas, {len(respuestas)} respuestas")
    medir_bertscore(respuestas, muestra)
