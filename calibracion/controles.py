"""Los dos controles negativos: semillas al azar uniformes y semillas apareadas por clase de grado.

Si la clase de una semilla no tiene candidatos libres se toma de la clase vecina mas cercana"""
import bisect
import os

import numpy as np

#configurable para corridas variantes. Mas sorteos estabilizan la banda del nulo y la vara del
#conteo, a costo lineal en computo
N_SORTEOS = int(os.environ.get("CRECIMIENTO_N_SORTEOS", "20"))

#conjuntos apareados sobre los que se corren los folds del nulo del recall: los primeros N de
#los N_SORTEOS ya sorteados, sin sortear nada nuevo. Miden cuanto recall da el grado solo. Se
#corre solo en el nivel de remocion FRAC_CON_CONTROL, ver recall.py
N_SORTEOS_RECALL = int(os.environ.get("CRECIMIENTO_N_SORTEOS_RECALL", "5"))


GRADO_EXACTO_HASTA = 7
#desde aca todos los hubs van a una sola clase
GRADO_HUB = 512
#los bordes inferiores de las clases por potencia de 2, escritos uno por uno
LIMITES_DE_CLASE = (8, 16, 32, 64, 128, 256, GRADO_HUB)


def clase_de_grado(grado):
    if grado <= GRADO_EXACTO_HASTA:
        return grado
    return GRADO_EXACTO_HASTA + bisect.bisect_right(LIMITES_DE_CLASE, grado)


def candidatos(red_corrida, no_semillas=frozenset()):
    "Los nodos del plano entre los que se sortean los controles"
    return sorted(n for n in red_corrida.nodes() if n not in no_semillas)

def semillas_uniformes(rng, candidatos_del_plano, n, excluir):
    "n nodos al azar uniforme entre los candidatos, sin usar semillas reales"
    elegibles = [c for c in candidatos_del_plano if c not in excluir]
    if len(elegibles) < n:
        raise ValueError(f"{len(elegibles)} candidatos para {n} semillas de control")
    return sorted(rng.choice(elegibles, size=n, replace=False))


def _mas_cercano(ordenados, valor):
    "el elemento de una lista ordenada mas cercano al valor. Ante empate de distancia se queda con el menor. Se hace mediante busqueda binaria"
    i = bisect.bisect_left(ordenados, valor)
    vecinos = []
    if i < len(ordenados):
        vecinos.append(ordenados[i])
    if i > 0:
        vecinos.append(ordenados[i - 1])
    return min(vecinos, key=lambda v: (abs(v - valor), v))


class _PoolPorGrado:
    def __init__(self, red_corrida, candidatos_del_plano, excluir):
        self._por_clase = {}
        for c in candidatos_del_plano:
            if c in excluir:
                continue
            grado = red_corrida.grado(c)
            self._por_clase.setdefault(clase_de_grado(grado), {}).setdefault(grado, []).append(c)
        for por_grado in self._por_clase.values():
            for nodos in por_grado.values():
                nodos.sort()
        self._clases = sorted(self._por_clase)

    def total(self):
        return sum(len(nodos) for por_grado in self._por_clase.values() for nodos in por_grado.values())

    def clase_disponible(self, clase):
        "La clase pedida si le quedan candidatos, o la clase vecina mas cercana. Ante empate se queda con la menor"
        if not self._clases:
            raise ValueError("sin candidatos libres para aparear por grado")
        return _mas_cercano(self._clases, clase)

    def tomar(self, rng, grado):
        "saca del pool un candidato para el grado pedido y devuelve (candidato, fuera_de_clase), donde fuera_de_clase dice si hubo que ir a una clase vecina"
        clase_pedida = clase_de_grado(grado)
        clase = self.clase_disponible(clase_pedida)
        por_grado = self._por_clase[clase]
        elegido_grado = _mas_cercano(sorted(por_grado), grado)
        libres = por_grado[elegido_grado]
        elegido = libres.pop(rng.integers(len(libres)))
        if not libres:
            del por_grado[elegido_grado]
        if not por_grado:
            del self._por_clase[clase]
            self._clases.remove(clase)
        return elegido, clase != clase_pedida


def semillas_apareadas_por_grado(rng, red_corrida, semillas_reales, candidatos_del_plano,
                                 excluir):
    pool = _PoolPorGrado(red_corrida, candidatos_del_plano, excluir)
    n = len(set(semillas_reales))
    if pool.total() < n:
        raise ValueError(f"{pool.total()} candidatos libres para {n} semillas de control: el "
                         f"apareo por grado necesita un nodo distinto por semilla")
    #orden determinista: por grado descendente, con el id como desempate
    por_dificultad = sorted(set(semillas_reales), key=lambda s: (-red_corrida.grado(s), s))
    elegidos = []
    fuera_de_clase = 0
    for semilla in por_dificultad:
        elegido, fuera = pool.tomar(rng, red_corrida.grado(semilla))
        elegidos.append(elegido)
        fuera_de_clase += int(fuera)
    return sorted(elegidos), fuera_de_clase


def generar_controles(seed_caso, red_corrida, semillas_reales, candidatos_del_plano,
                      n_sorteos=N_SORTEOS):
    excluir = set(semillas_reales)
    n = len(semillas_reales)
    resultado = {"apareado": [], "uniforme": [], "fuera_de_clase": []}
    for i in range(n_sorteos):
        rng = np.random.default_rng([seed_caso, i])
        apareadas, fuera = semillas_apareadas_por_grado(rng, red_corrida, semillas_reales,
                                                        candidatos_del_plano, excluir)
        resultado["apareado"].append(apareadas)
        resultado["fuera_de_clase"].append(fuera)
        resultado["uniforme"].append(
            semillas_uniformes(rng, candidatos_del_plano, n, excluir))
    return resultado
