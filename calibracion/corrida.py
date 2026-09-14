"""Una corrida de DIAMOnD dentro de un plano.

La fraccion de semillas en la LCC, que es cuantas de las semillas quedaron conectadas entre si dentro del modulo, se reconstruye con un union-find incremental: se parte de las semillas, se agregan los nodos en el orden en que DIAMOnD los agrego, y en cada paso se unen las aristas internas del modulo.

se arranca en la iteracion 0, que es el estado de las semillas solas antes de agregar nada. 

Lo unico que se excluye de la red es el ancla en aquellos casos en que la corrida es del tipo A -> A
"""
import os
import sys

import numpy as np
import pandas as pd

_AQUI = os.path.dirname(os.path.abspath(__file__))
#la red compacta y el port de DIAMOnD viven en expansion/, comunes a todos los grafos
sys.path.insert(0, os.path.join(_AQUI, "..", "expansion"))

from adyacencia import RedCompacta  
from diamond_algoritmo import DIAMOnD  

#iteraciones a tener en cuenta. Se puede fijar por entorno para una corrida variante, igual que
#N_POR_BIN en paso0_sorteo.py, sin tocar el codigo: CRECIMIENTO_PRESUPUESTO=200
PRESUPUESTO = int(os.environ.get("CRECIMIENTO_PRESUPUESTO", "100"))


def red_sin_ancla(red, ancla_id):
    """La misma red sin el nodo del ancla y sus aristas. Si el ancla no esta en la red devuelve la red tal cual"""
    if ancla_id not in red:
        return red
    ids = red._ids
    idx = np.flatnonzero(ids != ancla_id)
    matriz = red._matriz[np.ix_(idx, idx)]
    return RedCompacta(matriz, ids[idx])


def correr_diamond(red_corrida, semillas, presupuesto=PRESUPUESTO):
    """[(nodo, k, kb, p), ...] en orden de agregacion. Llama al  algoritmo de menche"""
    return DIAMOnD(red_corrida, semillas, presupuesto)


class _UnionFind:
    def __init__(self, elementos):
        self._padre = {e: e for e in elementos}
        self._tam = {e: 1 for e in elementos}

    def raiz(self, e):
        while self._padre[e] != e:
            self._padre[e] = self._padre[self._padre[e]]
            e = self._padre[e]
        return e

    def unir(self, a, b):
        ra, rb = self.raiz(a), self.raiz(b)
        if ra == rb:
            return
        if self._tam[ra] < self._tam[rb]:
            ra, rb = rb, ra
        self._padre[rb] = ra
        self._tam[ra] += self._tam[rb]


def estado_de_la_lcc(uf, semillas, en_modulo):
    """La componente conexa con mas semillas del modulo actual: cuantas semillas la integran y de cuantos nodos es en total. uf es el resultado del union find
    
    recorre las semillas, les pide la raiz a cad auna y acumula en por_raiz un contador por raiz. Al terminar por_raiz es un diccionario que dado un componente retorna la cantidad de semillas  
    """
    por_raiz = {}
    for s in semillas:
        raiz = uf.raiz(s)
        por_raiz[raiz] = por_raiz.get(raiz, 0) + 1
    raiz_lcc, semillas_en_lcc = max(por_raiz.items(), key=lambda kv: kv[1])
    lcc_tam = sum(1 for n in en_modulo if uf.raiz(n) == raiz_lcc)
    

    return semillas_en_lcc, lcc_tam


def traza_de_corrida(red_corrida, semillas, agregados):
    """Una fila por cada iteracion, con lo que hace falta para todas las curvas del experimento.

queda en las columnas: iteracion, nodo, grado, kb, semillas_en_lcc, frac_semillas_lcc, lcc_tam. frac_semillas_lcc es sobre el total de semillas de la corrida.
    """
    semillas = sorted(set(semillas))
    en_modulo = set(semillas)
    uf = _UnionFind(semillas)
    #aristas semilla- semilla presentes desde la iteracion 0:
    for s in semillas:
        for vecino in red_corrida.neighbors(s):
            if vecino in en_modulo:
                uf.unir(s, vecino)

    #la iteracion 0 son las semillas solas, sin ningun nodo agregado todavia. No hay nodo, asi que las tres columnas que lo describen quedan vacias, igual que en las filas arrastradas
    semillas_en_lcc, lcc_tam = estado_de_la_lcc(uf, semillas, en_modulo)
    filas = [{
        "iteracion": 0, "nodo": "",
        "grado": np.nan, "kb": np.nan,
        "semillas_en_lcc": semillas_en_lcc,
        "frac_semillas_lcc": semillas_en_lcc / len(semillas),
        "lcc_tam": lcc_tam}]

    #diamond devuelve tambien el p valor del nodo elegido, que no se guarda: es el criterio interno de DIAMOnD para elegir
    for iteracion, (nodo, k, kb, _p) in enumerate(agregados, start=1):
        uf._padre[nodo] = nodo
        uf._tam[nodo] = 1
        en_modulo.add(nodo)
        for vecino in red_corrida.neighbors(nodo):
            if vecino in en_modulo:
                uf.unir(nodo, vecino)

        semillas_en_lcc, lcc_tam = estado_de_la_lcc(uf, semillas, en_modulo)
        filas.append({
            "iteracion": iteracion, "nodo": nodo,
            "grado": float(k), "kb": float(kb),
            "semillas_en_lcc": semillas_en_lcc,
            "frac_semillas_lcc": semillas_en_lcc / len(semillas),
            "lcc_tam": lcc_tam})
    return pd.DataFrame(filas)
