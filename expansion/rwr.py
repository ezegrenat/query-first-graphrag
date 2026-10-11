"""RWR exacto sobre el grafo heterogeneo, con reinicio r en una distribucion de semillas.

Iteracion de potencias x = r * e + (1 - r) * P^T x, con P la transicion de grafo_heterogeneo.py (regla de MultiXrank). Un nodo sin vecinos pierde su masa en cada paso, lo que cambia la escala del puntaje y no el orden.
"""
import numpy as np

R = 0.5


def distribucion_uniforme(n, indices):
    e = np.zeros(n)
    e[indices] = 1 / len(indices)
    return e


def rwr_exacto(grafo, e, r=R, tolerancia=1e-10, max_iter=1000):
    """El RWR por iteracion de potencias, normalizado a suma 1."""
    PT = grafo.transicion.T.tocsr()
    x = e.copy()
    for _ in range(max_iter):
        nuevo = r * e + (1 - r) * (PT @ x)
        if np.abs(nuevo - x).sum() < tolerancia:
            x = nuevo
            break
        x = nuevo
    return x / x.sum()
