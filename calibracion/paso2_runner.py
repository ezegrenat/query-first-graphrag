"""El batch del experimento: por cada caso de resultados/casos.csv, la corrida real, sus
controles y sus folds de recall.

Por caso se corren (1 + 2) x N_SORTEOS corridas de DIAMOnD (la real, N_SORTEOS con semillas uniformes y N_SORTEOS con semillas apareadas por clase de grado), mas los folds de recall) N_FOLDS por cada uno de los tres niveles de remocion sobre las semillas reales, y N_FOLDS x
N_SORTEOS_RECALL del nulo en el nivel con control. Como resultado estan los parquet: 

- resultados/trazas/{celda}__{ancla}.parquet, con las trazas por iteracion de la corrida real y de las de control, distinguidas por las columnas fuente (real, uniforme, apareado) y sorteo. Las corridas apareadas llevan ademas semillas_fuera_de_clase: cuantas de sus semillas de control hubo que tomar de una clase de grado vecina porque la propia se agoto eso se puede revisar en controles.py). 

- resultados/recalls/{celda}__{ancla}.parquet, con la curva de recall completa de cada fold, junto n_escondidas y n_universo para poder dibujar la linea de azar sin recomputar. Los folds se corren en los tres niveles de remocion del paper (columna `frac_escondida`, 10%, 20% y 30%) sobre las semillas reales y, en el nivel FRAC_CON_CONTROL, tambien sobre los primeros N_SORTEOS_RECALL conjuntos apareados 

"""
import argparse
import os
import time
import zlib

import numpy as np
import pandas as pd

from celdas import CELDAS, ORDEN_CELDAS, PLANOS, RESULTADOS, conectar, obtener_plano, \
    nodos_que_no_pueden_ser_semilla, semillas_efectivas
from controles import N_SORTEOS_RECALL, candidatos, generar_controles
from corrida import PRESUPUESTO, correr_diamond, red_sin_ancla, traza_de_corrida
from paso0_sorteo import SEED_SELECCION
from recall import FRAC_CON_CONTROL, componente_alcanzable, curva_recall, folds_de_remocion, \
    folds_de_todos_los_niveles

DIR_TRAZAS = os.path.join(RESULTADOS, "trazas")
DIR_RECALLS = os.path.join(RESULTADOS, "recalls")


def seed_de_caso(celda_nombre, ancla):
    """Entero determinista por caso, derivado de la seed global
    """
    return zlib.crc32(f"{celda_nombre}|{ancla}".encode()) ^ SEED_SELECCION


def _ruta(directorio, celda, ancla):
    return os.path.join(directorio, f"{celda.nombre}__{ancla.replace(':', '_')}.parquet")


def caso_completo(celda, ancla):
    """Si el caso ya tiene sus dos parquet en disco"""
    return (os.path.exists(_ruta(DIR_TRAZAS, celda, ancla))
            and os.path.exists(_ruta(DIR_RECALLS, celda, ancla)))


def correr_caso(celda, ancla, semillas, red, dir_trazas=DIR_TRAZAS, dir_recalls=DIR_RECALLS,
                no_semillas=frozenset()):
    """Corre y persiste un caso completo. Los directorios de salida son parametrizables para que una corrida exploratoria no pise los  resultados de la principal
    """
    os.makedirs(dir_trazas, exist_ok=True)
    os.makedirs(dir_recalls, exist_ok=True)
    seed = seed_de_caso(celda.nombre, ancla)
    red_corrida = red_sin_ancla(red, ancla)
    #cambio respecto de optimuskg: los grupos BERT no se sortean como semilla de control
    candidatos_del_plano = candidatos(red_corrida, no_semillas)

    #la corrida real y las de control, todas al mismo parquet
    trazas = []

    def _agregar_traza(fuente, sorteo, conjunto_semilla, fuera_de_clase=np.nan):
        agregados = correr_diamond(red_corrida, conjunto_semilla, PRESUPUESTO)
        traza = traza_de_corrida(red_corrida, conjunto_semilla, agregados)
        traza.insert(0, "fuente", fuente)
        traza.insert(1, "sorteo", sorteo)
        traza["n_semillas"] = len(conjunto_semilla)
        #solo tiene sentido en las corridas apareadas, en las demas queda vacio
        traza["semillas_fuera_de_clase"] = fuera_de_clase
        trazas.append(traza)

    _agregar_traza("real", 0, semillas)
    controles = generar_controles(seed, red_corrida, semillas, candidatos_del_plano)
    for i, conjunto in enumerate(controles["uniforme"]):
        _agregar_traza("uniforme", i, conjunto)
    for i, (conjunto, fuera) in enumerate(zip(controles["apareado"], controles["fuera_de_clase"])):
        _agregar_traza("apareado", i, conjunto, fuera)
    pd.concat(trazas).to_parquet(_ruta(dir_trazas, celda, ancla), index=False)

    #recall: los folds sobre las semillas reales, en los tres niveles de remocion del paper
    rng_folds = np.random.default_rng([seed, 10_001]) #generador de azar que decide que semillas se esconden en cada fold del recall real
    curvas = []

    def _agregar_curva(fuente, sorteo, frac, fold, visibles, escondidas):
        agregados = correr_diamond(red_corrida, visibles, PRESUPUESTO)
        curva = curva_recall(agregados, escondidas)
        curva.insert(0, "fuente", fuente)
        curva.insert(1, "sorteo", sorteo)
        curva.insert(2, "frac_escondida", frac)
        curva.insert(3, "fold", fold)
        curva["n_escondidas"] = len(escondidas)
        #universo del azar: la componente alcanzable desde las visibles, no el plano entero, y se le restan las visibles porque ya estan en el modulo y no pueden ser un acierto
        curva["n_universo"] = (len(componente_alcanzable(red_corrida, visibles))
                               - len(visibles))
        curvas.append(curva)

    for frac, fold, visibles, escondidas in folds_de_todos_los_niveles(rng_folds, semillas):
        _agregar_curva("real", 0, frac, fold, visibles, escondidas)

    #el nulo del recall: los mismos folds sobre los primeros N_SORTEOS_RECALL conjuntos apareados. Se esconde el 30% de un conjunto de semillas al azar del mismo grado y se mide cuanto de eso recupera DIAMOnD
    rng_folds_nulo = np.random.default_rng([seed, 10_002])
    for i, conjunto in enumerate(controles["apareado"][:N_SORTEOS_RECALL]):
        for fold, (visibles, escondidas) in enumerate(folds_de_remocion(rng_folds_nulo, conjunto,
                                                                        FRAC_CON_CONTROL)):
            _agregar_curva("apareado", i, FRAC_CON_CONTROL, fold, visibles, escondidas)
    pd.concat(curvas).to_parquet(_ruta(dir_recalls, celda, ancla), index=False)


def _submuestra_mini(casos, n_por_celda):
    """n_por_celda casos por celda, repartidos entre bins.

    Es la escalera de validacion: probar el pipeline entero con pocos casos antes de gastar el batch completo. Toma bajo y alto primero, para tener los dos extremos de tamaño. Determinista:
    los primeros de cada bin en el orden de casos.csv, que ya viene de un sorteo con seed.
    """
    partes = []
    for _, del_grupo in casos.groupby("celda", sort=False):
        #diccionario con tres tablas: casos del bin bajo, del alto y luego del bajo (en ese orden) 
        por_bin = {b: del_grupo[del_grupo["bin"] == b] for b in ("bajo", "alto", "medio")}
        elegidos = []
        i = 0
        while len(elegidos) < n_por_celda and i < max(len(v) for v in por_bin.values()):
        #en cada ronda se toma el caso numero i del bin bajo, luego del alto y despues del medio
            for b in ("bajo", "alto", "medio"):
                if len(elegidos) < n_por_celda and i < len(por_bin[b]):
                    elegidos.append(por_bin[b].iloc[i])
            i += 1
        partes.append(pd.DataFrame(elegidos))
    return pd.concat(partes, ignore_index=True)


def main(nombres_celdas=None, mini=None):
    os.makedirs(DIR_TRAZAS, exist_ok=True)
    os.makedirs(DIR_RECALLS, exist_ok=True)
    ruta_casos = os.path.join(RESULTADOS, "casos.csv")
    if not os.path.exists(ruta_casos):
        raise SystemExit(f"falta {ruta_casos}: correr paso0_sorteo.py antes del batch")
    casos = pd.read_csv(ruta_casos)
    if nombres_celdas:
        casos = casos[casos["celda"].isin(nombres_celdas)]
    if mini:
        casos = _submuestra_mini(casos, mini)

    gds = conectar()
    planos_cargados = {}

    for nombre_celda in ORDEN_CELDAS:
        del_grupo = casos[casos["celda"] == nombre_celda]
        if del_grupo.empty:
            continue
        celda = CELDAS[nombre_celda]
        if celda.plano not in planos_cargados:
            planos_cargados[celda.plano] = obtener_plano(gds, PLANOS[celda.plano], verbose=False)
        red = planos_cargados[celda.plano]
        semillas = semillas_efectivas(gds, celda, red)
        no_semillas = nodos_que_no_pueden_ser_semilla(gds, PLANOS[celda.plano])

        pendientes = [a for a in del_grupo["ancla"] if not caso_completo(celda, a)]
        print(f"[{nombre_celda}] {len(pendientes)} casos pendientes de {len(del_grupo)}", flush=True)
        for n, ancla in enumerate(pendientes, start=1):
            t0 = time.time()
            correr_caso(celda, ancla, semillas[ancla], red, no_semillas=no_semillas)
            print(f"  [{nombre_celda}] {n}/{len(pendientes)} {ancla} "
                  f"ok ({time.time() - t0:.1f}s)", flush=True)
    print("batch completo", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--celdas", nargs="*", default=None)
    p.add_argument("--mini", type=int, default=None,
                   help="correr solo N casos por celda (repartidos entre bins)")
    args = p.parse_args()
    main(args.celdas, mini=args.mini)
