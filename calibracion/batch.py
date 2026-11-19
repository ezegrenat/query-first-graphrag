"""El batch del experimento: por cada caso de resultados_grafo_laboratorio/casos.csv se hace la corrida real, sus
controles y sus folds de recall.

Como resultado estan los parquet: 

- resultados_grafo_laboratorio/trazas/{celda}__{entidad}.parquet, con las trazas por iteracion de la corrida real y de las de control, distinguidas por las columnas fuente. 

- resultados_grafo_laboratorio/recalls/{celda}__{entidad}.parquet, con la curva de recall completa de cada fold, junto n_escondidas y n_universo para poder dibujar la linea de azar sin recomputar. Los folds se corren en tres niveles de remocion ( 10%, 20% y 30%) sobre las semillas reales y, en el nivel FRAC_CON_CONTROL, tambien sobre los primeros N_SORTEOS_RECALL conjuntos apareados 

"""
import argparse
import os
import time
import zlib

import numpy as np
import pandas as pd

from celdas import PLANOS, RESULTADOS, nodos_que_no_pueden_ser_semilla, obtener_plano
from planos_y_pasos import CELDAS, ORDEN_CELDAS, conectar, semillas_efectivas
from controles import N_SORTEOS_RECALL, candidatos, generar_controles
from corrida import PRESUPUESTO, correr_diamond, red_sin_entidad, traza_de_corrida
from sorteo import SEED_SELECCION
from recall import FRAC_CON_CONTROL, componente_alcanzable, curva_recall, folds_de_remocion, \
    folds_de_todos_los_niveles

DIR_TRAZAS = os.path.join(RESULTADOS, "trazas")
DIR_RECALLS = os.path.join(RESULTADOS, "recalls")


def seed_de_caso(celda_nombre, entidad):
    return zlib.crc32(f"{celda_nombre}|{entidad}".encode()) ^ SEED_SELECCION


def _ruta(directorio, celda, entidad):
    return os.path.join(directorio, f"{celda.nombre}__{entidad.replace(':', '_')}.parquet")


def caso_completo(celda, entidad):
    return (os.path.exists(_ruta(DIR_TRAZAS, celda, entidad))
            and os.path.exists(_ruta(DIR_RECALLS, celda, entidad)))


def correr_caso(celda, entidad, semillas, red, dir_trazas=DIR_TRAZAS, dir_recalls=DIR_RECALLS,
                no_semillas=frozenset()):
    os.makedirs(dir_trazas, exist_ok=True)
    os.makedirs(dir_recalls, exist_ok=True)
    seed = seed_de_caso(celda.nombre, entidad)
    red_corrida = red_sin_entidad(red, entidad)
    #los grupos BERT no se sortean como semilla de control
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
    pd.concat(trazas).to_parquet(_ruta(dir_trazas, celda, entidad), index=False)

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
    pd.concat(curvas).to_parquet(_ruta(dir_recalls, celda, entidad), index=False)


def _submuestra_mini(casos, n_por_celda):
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
        raise SystemExit(f"falta {ruta_casos}: correr sorteo.py antes del batch")
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

        pendientes = [a for a in del_grupo["entidad"] if not caso_completo(celda, a)]
        print(f"[{nombre_celda}] {len(pendientes)} casos pendientes de {len(del_grupo)}", flush=True)
        for n, entidad in enumerate(pendientes, start=1):
            t0 = time.time()
            correr_caso(celda, entidad, semillas[entidad], red, no_semillas=no_semillas)
            print(f"  [{nombre_celda}] {n}/{len(pendientes)} {entidad} "
                  f"ok ({time.time() - t0:.1f}s)", flush=True)
    print("batch completo", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--celdas", nargs="*", default=None)
    p.add_argument("--mini", type=int, default=None,
                   help="correr solo N casos por celda (repartidos entre bins)")
    args = p.parse_args()
    main(args.celdas, mini=args.mini)
