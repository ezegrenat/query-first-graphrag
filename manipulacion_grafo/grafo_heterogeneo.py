"""El grafo heterogeneo donde camina el RWR: Gene, Disease y Drug con sus seis relaciones.

Los tres planos son los de la seleccion de subgrafo (PPI, DISEASE_DISEASE sin grupos BERT y DRUG_DRUG desde
UMBRAL_DRUG) y se leen del cache de esta carpeta. Las tres relaciones entre tipos (GDA, DRUG_TARGET e
INDICATION, sin grupos BERT) se traen una vez de Neo4j y se guardan en cache_bipartitas.parquet. Todo va a una
sola matriz de adyacencia sin pesos, con los nodos en tres bloques en el orden de TIPOS.

La probabilidad de pasar de un nodo v de tipo alfa a un vecino x es la de MultiXrank (Baptista et al. 2022,
TransitionMatrix.py), con cada tipo como un multiplex de una sola capa. Si S son los otros tipos donde v
tiene vecinos y lam[beta][alfa] la probabilidad de saltar de alfa a beta:
- si v tiene vecinos de su tipo, va a cada uno con (1 - suma de lam[beta][alfa] sobre S) / grado_alfa(v), y
  a cada vecino de tipo beta con lam[beta][alfa] / grado_beta(v);
- si v no tiene vecinos de su tipo, el salto se reparte solo entre los tipos de S, en proporcion a lam.
Un nodo sin vecinos de otro tipo se queda siempre en su plano.
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import sparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from planos_y_pasos import PLANOS, obtener_plano, plano_drug  # noqa: E402

TIPOS = ("Gene", "Disease", "Drug")
UMBRAL_DRUG = 0.8
#MultiXrank por defecto: la misma probabilidad para cada salto entre tipos
LAMBDA_UNIFORME = np.full((3, 3), 1 / 3)

CACHE_PLANOS = os.path.join(AQUI, "cache_planos")
CACHE_BIPARTITAS = os.path.join(AQUI, "cache_bipartitas.parquet")

#las tres relaciones entre tipos, con los grupos BERT afuera como en las cosechas de planos_y_pasos.py
CONSULTA_BIPARTITAS = {
    "GDA": "MATCH (a:Gene)-[:GDA]-(b:Disease) WHERE NOT b.es_grupo_bert RETURN DISTINCT a.id AS a, b.id AS b",
    "DRUG_TARGET": "MATCH (a:Drug)-[:DRUG_TARGET]-(b:Gene) RETURN DISTINCT a.id AS a, b.id AS b",
    "INDICATION": "MATCH (a:Drug)-[:INDICATION]-(b:Disease) WHERE NOT b.es_grupo_bert RETURN DISTINCT a.id AS a, b.id AS b",
}
TIPOS_BIPARTITAS = {"GDA": ("Gene", "Disease"), "DRUG_TARGET": ("Drug", "Gene"), "INDICATION": ("Drug", "Disease")}


def bipartitas(gds):
    """Las aristas entre tipos como DataFrame (relacion, tipo_a, a, tipo_b, b), del cache o de Neo4j."""
    if os.path.exists(CACHE_BIPARTITAS):
        return pd.read_parquet(CACHE_BIPARTITAS)
    partes = []
    for relacion, consulta in CONSULTA_BIPARTITAS.items():
        filas = gds.run_cypher(consulta)
        tipo_a, tipo_b = TIPOS_BIPARTITAS[relacion]
        partes.append(pd.DataFrame({"relacion": relacion, "tipo_a": tipo_a, "a": filas["a"].astype(str),
                                    "tipo_b": tipo_b, "b": filas["b"].astype(str)}))
    tabla = pd.concat(partes, ignore_index=True)
    tabla.to_parquet(CACHE_BIPARTITAS, index=False)
    return tabla


class GrafoHeterogeneo:
    """La adyacencia de los tres tipos juntos, los nodos como (label, id) y la matriz de transicion."""

    def __init__(self, planos, aristas_entre_tipos, lam=LAMBDA_UNIFORME):
        #los nodos: los de cada plano y los extremos de las relaciones entre tipos, por tipo y ordenados
        ids_por_tipo = {tipo: set() for tipo in TIPOS}
        for tipo, plano in zip(TIPOS, planos):
            ids_por_tipo[tipo].update(str(i) for i in plano._ids)
        for fila in aristas_entre_tipos.itertuples():
            ids_por_tipo[fila.tipo_a].add(fila.a)
            ids_por_tipo[fila.tipo_b].add(fila.b)
        self.nodos = [(tipo, i) for tipo in TIPOS for i in sorted(ids_por_tipo[tipo])]
        self.indice = {nodo: k for k, nodo in enumerate(self.nodos)}
        self.tipo = np.array([TIPOS.index(tipo) for tipo, _ in self.nodos])
        self.n = len(self.nodos)

        #las aristas de los planos, pasadas de los indices de cada plano a los del grafo entero
        filas, columnas = [], []
        for tipo, plano in zip(TIPOS, planos):
            a = plano._matriz.tocoo()
            traduccion = np.array([self.indice[(tipo, str(i))] for i in plano._ids])
            filas.append(traduccion[a.row])
            columnas.append(traduccion[a.col])
        #las aristas entre tipos, en los dos sentidos
        extremo_a = np.array([self.indice[(t, i)] for t, i in zip(aristas_entre_tipos["tipo_a"], aristas_entre_tipos["a"])])
        extremo_b = np.array([self.indice[(t, i)] for t, i in zip(aristas_entre_tipos["tipo_b"], aristas_entre_tipos["b"])])
        filas += [extremo_a, extremo_b]
        columnas += [extremo_b, extremo_a]
        filas, columnas = np.concatenate(filas), np.concatenate(columnas)
        adyacencia = sparse.csr_matrix((np.ones(len(filas)), (filas, columnas)), shape=(self.n, self.n))
        #una arista repetida suma 2 al construir la matriz; se deja en 1 porque el grafo no tiene pesos
        adyacencia.data[:] = 1.0
        adyacencia.sort_indices()
        self.adyacencia = adyacencia
        self.grado = np.diff(adyacencia.indptr)
        self.transicion = self.matriz_de_transicion(lam)

    def matriz_de_transicion(self, lam):
        """P[v, x], la probabilidad de pasar de v a x, con la regla de MultiXrank del docstring del modulo."""
        a = self.adyacencia.tocoo()
        origen, destino = a.row, a.col
        tipo_origen, tipo_destino = self.tipo[origen], self.tipo[destino]
        #grado_por_tipo[v, beta]: cuantos vecinos de tipo beta tiene v
        grado_por_tipo = np.zeros((self.n, 3))
        np.add.at(grado_por_tipo, (origen, tipo_destino), 1)

        #salto[v]: la suma de lam[beta][alfa] sobre los otros tipos donde v tiene vecinos
        salto = np.zeros(self.n)
        for alfa in range(3):
            for beta in range(3):
                if beta != alfa:
                    salto += (self.tipo == alfa) * (grado_por_tipo[:, beta] > 0) * lam[beta, alfa]
        propio = grado_por_tipo[np.arange(self.n), self.tipo]

        mismo_tipo = tipo_origen == tipo_destino
        peso = np.empty(len(origen))
        peso[mismo_tipo] = (1 - salto[origen[mismo_tipo]]) / propio[origen[mismo_tipo]]
        cruce = ~mismo_tipo
        o, beta = origen[cruce], tipo_destino[cruce]
        lam_salto = lam[beta, tipo_origen[cruce]]
        #sin vecinos de su tipo, el salto se renormaliza entre los tipos a los que puede ir
        lam_salto = np.where(propio[o] > 0, lam_salto, lam_salto / salto[o])
        peso[cruce] = lam_salto / grado_por_tipo[o, beta]

        P = sparse.csr_matrix((peso, (origen, destino)), shape=(self.n, self.n))
        P.sort_indices()
        suma = np.asarray(P.sum(axis=1)).ravel()
        assert np.allclose(suma[self.grado > 0], 1.0), "alguna fila de la transicion no suma 1"
        return P

    def indices(self, nodos):
        """Los indices en el grafo de una coleccion de (label, id); los que no estan en el grafo se ignoran."""
        return np.array(sorted({self.indice[n] for n in nodos if n in self.indice}), dtype=np.int64)


def cargar(gds, lam=LAMBDA_UNIFORME):
    """El GrafoHeterogeneo con los planos del cache de esta carpeta y las relaciones entre tipos."""
    planos = [obtener_plano(gds, PLANOS["gene"], False, CACHE_PLANOS),
              obtener_plano(gds, PLANOS["disease"], False, CACHE_PLANOS),
              obtener_plano(gds, plano_drug(UMBRAL_DRUG), False, CACHE_PLANOS)]
    return GrafoHeterogeneo(planos, bipartitas(gds), lam)
