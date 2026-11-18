"""Recall cruzado. Se esconde cerca del 30% de las semillas, se corre DIAMOnD con las visibles, y se mide que fraccion de las escondidas aparece entre los primeros rank nodos agregados

La linea de "esperable por azar" usa como universo la componente alcanzable desde las semillas visibles (union de las componentes conexas que tocan, ver componente_alcanzable), no el plano entero
"""
import pandas as pd

FRAC_ESCONDIDA = 0.3
N_FOLDS = 5


FRACCIONES_ESCONDIDAS = (0.1, 0.2, 0.3)

FRAC_CON_CONTROL = 0.3


def componente_alcanzable(red, nodos_iniciales):
    """Todos los nodos que DIAMOnD podria llegar a agregar alguna vez desde nodos_iniciales: la union de las componentes conexas que tocan. Recorrido en anchura desde todos los nodos iniciales a la vez, asi que si las semillas visibles caen en mas de una componente el resultado es la union de todas, no solo la de la primera."""
    visitados = set(nodos_iniciales)
    frontera = list(nodos_iniciales)
    while frontera:
        siguiente = []
        for n in frontera:
            for vecino in red.neighbors(n):
                if vecino not in visitados:
                    visitados.add(vecino)
                    siguiente.append(vecino)
        frontera = siguiente
    return visitados


def folds_de_remocion(rng, semillas, frac=FRAC_ESCONDIDA, n_folds=N_FOLDS):
    """dado un conjunto de semillas, una fraccion y una determinada cantidad de folds devuelve un par de las semillas que quedaran
    visibles y aquellas que quedaran escondidas"""
    semillas = sorted(set(semillas))
    n_esconder = max(1, round(len(semillas) * frac))
    folds = []
    for _ in range(n_folds):
        escondidas = sorted(rng.choice(semillas, size=n_esconder, replace=False))
        visibles = sorted(set(semillas) - set(escondidas))
        folds.append((visibles, escondidas))
    return folds


def folds_de_todos_los_niveles(rng, semillas, fracciones=FRACCIONES_ESCONDIDAS,
                              n_folds=N_FOLDS):
    """[(frac_escondida, fold, visibles, escondidas), ...] para los tres niveles de remocion.

    Los folds de cada nivel salen del mismo generador y en orden de nivel creciente, asi que la seed del caso fija la lista entera y dos corridas del mismo caso esconden lo mismo.
    """
    de_todos = []
    for frac in fracciones:
        for i, (visibles, escondidas) in enumerate(folds_de_remocion(rng, semillas, frac, n_folds)):
            de_todos.append((frac, i, visibles, escondidas))
    return de_todos


def curva_recall(agregados, escondidas):
    """calcula fraccion de las escondidas entre los primeros rank nodos agregados.

    en agregados se tiene el retorno de DIAMOnD en orden. La curva completa se persiste por fold para poder calcular el intervalo de confianza sin recomputar nada.
    """
    escondidas = set(escondidas)
    aciertos = 0
    filas = []
    for rank, (nodo, _k, _kb, _p) in enumerate(agregados, start=1):
        if nodo in escondidas:
            aciertos += 1
        filas.append({"rank": rank, "recall": aciertos / len(escondidas)})
    return pd.DataFrame(filas)
