"""La fraccion de semillas en su propia componente antes de que DIAMOnD agregue nada, con su
significancia contra sorteos uniformes de nodos del plano: es la Fig. 1B a 1D y la Tabla 1 del
paper de DIAMOnD (Ghiassian, Menche y Barabasi, 2015).

No corre DIAMOnD: mide si el conjunto que cada celda cosecha ya viene conectado en el plano donde
va a expandir, contando solo las aristas entre las semillas mismas. Por eso se puede calcular
sobre los 1.170 casos de la corrida ya hecha sin recorrer nada, con una consulta a Neo4j por
celda y sorteos baratos (no llaman a DIAMOnD).

El umbral de significancia es z > 1,6, el mismo que usa el paper (49 de sus 70 enfermedades lo
superan). El p empirico es la fraccion de los sorteos que igualan o superan la fraccion real,
como en la Tabla 1.
"""
import os
import zlib

import numpy as np
import pandas as pd

from celdas import CELDAS, ORDEN_CELDAS, RESULTADOS, conectar, obtener_plano, PLANOS, \
    nodos_que_no_pueden_ser_semilla, semillas_efectivas
from controles import candidatos
from corrida import red_sin_ancla

N_SORTEOS = 1000
SEED_ITERACION0 = 43   #distinta de la seed 42 del sorteo de casos, para que no se solapen


def seed_de_caso(nombre_celda, ancla):
    """Entero determinista por caso, con crc32 y no con hash: el hash de strings cambia en cada proceso salvo que PYTHONHASHSEED este fijado, y este script se corre a mano, fuera del batch que la fija. Misma derivacion que runner.seed_de_caso, con la seed propia de este paso."""
    return zlib.crc32(f"{nombre_celda}|{ancla}".encode()) ^ SEED_ITERACION0


def frac_lcc(red, nodos):
    """La fraccion de `nodos` que cae en su propia componente conexa mayor, contando solo las
    aristas entre ellos mismos. Union-find liviano, sin dependencias, porque se llama miles de
    veces por caso.
    """
    nodos = list(nodos)
    padre = {n: n for n in nodos}

    def raiz(n):
        while padre[n] != n:
            padre[n] = padre[padre[n]]
            n = padre[n]
        return n

    en_el_conjunto = set(nodos)
    for n in nodos:
        for vecino in red.neighbors(n):
            if vecino in en_el_conjunto:
                a, b = raiz(n), raiz(vecino)
                if a != b:
                    padre[a] = b

    tamanos = {}
    for n in nodos:
        r = raiz(n)
        tamanos[r] = tamanos.get(r, 0) + 1
    return max(tamanos.values()) / len(nodos)


def z_score_iteracion0(red_corrida, semillas, candidatos_del_plano, n_sorteos=N_SORTEOS, seed=0):
    """(frac_real, media_nulo, desvio_nulo, z, p_empirico) contra sorteos uniformes del mismo
    tamano que semillas. z y p_empirico son NaN si el desvio del nulo es cero (semillas
    demasiado pocas o plano demasiado ralo para que el nulo tenga variacion).
    """
    frac_real = frac_lcc(red_corrida, semillas)
    rng = np.random.default_rng(seed)
    n = len(set(semillas))
    fracciones_nulo = np.empty(n_sorteos)
    for i in range(n_sorteos):
        sorteo = rng.choice(candidatos_del_plano, size=n, replace=False)
        fracciones_nulo[i] = frac_lcc(red_corrida, sorteo)
    media, desvio = fracciones_nulo.mean(), fracciones_nulo.std()
    z = (frac_real - media) / desvio if desvio > 0 else np.nan
    p_empirico = (fracciones_nulo >= frac_real).mean()
    return frac_real, media, desvio, z, p_empirico


def main():
    ruta_casos = os.path.join(RESULTADOS, "casos.csv")
    if not os.path.exists(ruta_casos):
        raise SystemExit(f"falta {ruta_casos}: correr paso0_sorteo.py antes")
    casos = pd.read_csv(ruta_casos)

    gds = conectar()
    filas = []
    for nombre_celda in ORDEN_CELDAS:
        del_celda = casos[casos["celda"] == nombre_celda]
        if del_celda.empty:
            continue
        celda = CELDAS[nombre_celda]
        red = obtener_plano(gds, PLANOS[celda.plano], verbose=False)
        semillas_por_ancla = semillas_efectivas(gds, celda, red)
        #cambio respecto de optimuskg: los grupos BERT no se sortean como semilla de control
        no_semillas = nodos_que_no_pueden_ser_semilla(gds, PLANOS[celda.plano])

        for _, fila in del_celda.iterrows():
            ancla = fila["ancla"]
            if ancla not in semillas_por_ancla:
                continue
            red_corrida = red_sin_ancla(red, ancla)
            candidatos_del_plano = candidatos(red_corrida, no_semillas)
            frac_real, media, desvio, z, p = z_score_iteracion0(
                red_corrida, semillas_por_ancla[ancla], candidatos_del_plano,
                seed=seed_de_caso(nombre_celda, ancla))
            filas.append({
                "celda": nombre_celda, "origen": celda.origen, "plano": celda.plano,
                "bin": fila["bin"], "ancla": ancla, "n_semillas": fila["n_semillas"],
                "frac_lcc_inicial": frac_real, "media_nulo_uniforme": media,
                "desvio_nulo_uniforme": desvio, "z": z, "p_empirico": p})
        print(f"[{nombre_celda}] {len(del_celda)} anclas", flush=True)

    tabla = pd.DataFrame(filas)
    tabla.to_csv(os.path.join(RESULTADOS, "iteracion0_casos.csv"), index=False)

    resumen = tabla.groupby("celda").agg(
        casos=("ancla", "size"),
        frac_lcc_inicial_mediana=("frac_lcc_inicial", "median"),
        z_mediana=("z", "median"),
        significativas=("z", lambda s: int((s > 1.6).sum())),
    ).reindex([c for c in ORDEN_CELDAS if c in set(tabla["celda"])])
    resumen["frac_significativas"] = (resumen["significativas"] / resumen["casos"]).round(2)
    resumen.to_csv(os.path.join(RESULTADOS, "iteracion0_celdas.csv"))
    print()
    print(resumen.round(3).to_string())
    print(f"\n-> resultados/iteracion0_casos.csv y iteracion0_celdas.csv ({len(tabla)} casos)")


if __name__ == "__main__":
    main()
