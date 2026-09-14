"""Los dos controles negativos: semillas al azar uniformes y semillas apareadas por clase de grado. Para cada corrida real se corre DIAMOnD tambien desde N nodos al azar del mismo plano. 
Como se aparea: cada semilla real se cambia por un candidato libre de su misma clase de grado, eligiendo dentro de la clase el grado mas cercano al de ella y sorteando entre los candidatos de ese grado. Las clases son el grado exacto hasta GRADO_EXACTO_HASTA (ahi el pool sobra en todos los planos), potencias de 2 desde 8 (8 a 15, 16 a 31, ...) 

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
    """La clase de apareo de un grado, como un entero que crece con el grado: el propio grado hasta GRADO_EXACTO_HASTA, y desde ahi una clase por cada borde de LIMITES_DE_CLASE que el grado alcanza (8 a 15 es la 8, 16 a 31 la 9, ..., 256 a 511 la 13, y 512 o mas la 14)"""
    if grado <= GRADO_EXACTO_HASTA:
        return grado
    return GRADO_EXACTO_HASTA + bisect.bisect_right(LIMITES_DE_CLASE, grado)


def candidatos(red_corrida, no_semillas=frozenset()):
    """Los nodos del plano entre los que se sortean los controles, en orden fijo para hacerlo reproducible. Se sacan los que nunca pueden ser semilla real (los grupos BERT, cuando estan en el plano), porque si no el nulo podria sortear nodos que la corrida real no puede tener."""
    #cambio respecto de optimuskg: el parametro no_semillas, vacio por defecto, asi que sin grupos el sorteo es identico
    return sorted(n for n in red_corrida.nodes() if n not in no_semillas)

def semillas_uniformes(rng, candidatos_del_plano, n, excluir):
    """n nodos al azar uniforme entre los candidatos, sin usar semillas reales."""
    elegibles = [c for c in candidatos_del_plano if c not in excluir]
    if len(elegibles) < n:
        raise ValueError(f"{len(elegibles)} candidatos para {n} semillas de control")
    return sorted(rng.choice(elegibles, size=n, replace=False))


def _mas_cercano(ordenados, valor):
    """El elemento de una lista ordenada mas cercano al valor. Ante empate de distancia se queda con el menor. Se hace mediante busqueda binaria"""
    i = bisect.bisect_left(ordenados, valor)
    vecinos = []
    if i < len(ordenados):
        vecinos.append(ordenados[i])
    if i > 0:
        vecinos.append(ordenados[i - 1])
    return min(vecinos, key=lambda v: (abs(v - valor), v))


class _PoolPorGrado:
    """Candidatos libres agrupados por clase de grado y, dentro de cada clase, por grado exacto. Se pide un candidato para un grado y devuelve el mas cercano dentro de la clase de ese grado, o de la clase vecina si la suya se agoto."""

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
        """La clase pedida si le quedan candidatos, o la clase vecina mas cercana (ante empate se queda con la menor)"""
        if not self._clases:
            raise ValueError("sin candidatos libres para aparear por grado")
        return _mas_cercano(self._clases, clase)

    def grado_mas_cercano(self, grado):
        """El grado libre mas cercano al pedido dentro de la clase disponible para ese grado"""
        clase = self.clase_disponible(clase_de_grado(grado))
        return _mas_cercano(sorted(self._por_clase[clase]), grado)

    def tomar(self, rng, grado):
        """Saca del pool un candidato para el grado pedido y devuelve (candidato, fuera_de_clase), donde fuera_de_clase dice si hubo que ir a una clase vecina."""
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
    """(semillas de control, cuantas quedaron fuera de su clase de grado): un nodo de control por semilla real, de su misma clase de grado y del grado mas cercano dentro de ella. Las semillas se recorren de mayor a menor grado porque las de grado alto son las dificiles de aparear, son priorizadas"""
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
    """{"apareado": [...], "uniforme": [...], "fuera_de_clase": [...]}: n_sorteos conjuntos de semillas de cada tipo, y por cada conjunto apareado cuantas de sus semillas se tomaron de una clase vecina."""
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
