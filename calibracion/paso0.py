"""Paso 0: distribuciones, bins y seleccion de los casos que va a correr el experimento. Genera cuatro salidas. 
1. resultados/paso0_distribuciones.pdf, dos paginas: la CCDF de grado de cada capa bipartita por tipo de nodo, y la CCDF de grado de cada plano homogeneo, las dos en log-log 

2. resultados/paso0_celdas.csv, una fila por celda con el tamaño del plano, las anclas candidatas y los bordes efectivos de cada bin. 

3. resultados/casos.csv, los casos del experimento: N_POR_BIN anclas por bin por celda, sorteadas con una seed que queda registrada en el propio CSV. 

4. resultados/descartadas_sin_control.csv y resultados/celdas_sin_pool.csv, el registro de lo que quedo afuera y por que. Los bins se arman por rango: las anclas elegibles se ordenan por cantidad de semillas y se parten en tres grupos del mismo tamaño."""
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt 
from matplotlib.backends.backend_pdf import PdfPages  

from celdas import CELDAS, CELDAS_POR_PLANO, MIN_SEMILLAS, ORDEN_CELDAS, PLANOS, RESULTADOS, \
    conectar, cosechar, obtener_plano, semillas_efectivas

#La unica capa bipartita del grafo entre los dos tipos del alcance, en el orden en que se dibujan, y la celda cuya consulta de
#cosecha las trae. Las dos celdas de cada par comparten la relacion, asi que alcanza con una.
CAPAS_BIPARTITAS = {
    "disease_gene": "disease_a_gene",
}

SEED_SELECCION = 42          

N_POR_BIN = int(os.environ.get("CRECIMIENTO_N_POR_BIN", "30"))
BINS = ("bajo", "medio", "alto")


def ccdf(valores):
    """Retorna (x, fraccion de valores >= x) con un punto por valor distinto, para graficar en log-log."""
    #cambio respecto de optimuskg: un punto por valor distinto y no uno por observacion. Con grados
    #enteros repetidos, un punto por observacion dibujaba en cada grado una columna vertical que
    #iba de P(K >= k) a P(K >= k+1), y en planos con muchos empates (disease) se veia como escalones
    x, cuantos = np.unique(np.asarray(valores), return_counts=True)
    #fraccion de observaciones con valor >= x[i]: suma acumulada de los conteos desde el final
    y = cuantos[::-1].cumsum()[::-1] / cuantos.sum()
    return x, y


def con_control_construible(semillas_por_ancla, n_candidatos):
    """Cada corrida real tiene N semillas. El control reemplaza esas N semillas por N nodos distintos del mismo plano y esos nodos no pueden ser semillas reales, porque si no el control se parecería a la real por construcción. Entonces hay dos restricciones a la vez: hacen falta N nodos, y hay que sacarlos de un pool al que primero se le quitaron las N semillas.
    """
    limite = n_candidatos / 2
    quedan = {}
    descartadas = {}
    for ancla, semillas in semillas_por_ancla.items():
        if len(semillas) <= limite:
            quedan[ancla] = semillas
        else:
            descartadas[ancla] = len(semillas)
    return quedan, descartadas


def bins_por_rango(semillas_por_ancla, piso_semillas=MIN_SEMILLAS, n_por_bin=N_POR_BIN):
    """{ancla: bin} para las elegibles, en tres grupos del mismo tamaño.

    Las elegibles se ordenan por (cantidad de semillas, id) y se parten en tres. El id desempata para que el resultado no dependa del orden en que vino el diccionario. Da error si no alcanzan para llenar los tres bins
    """
    elegibles = []
    for ancla, semillas in semillas_por_ancla.items():
        if len(semillas) >= piso_semillas:
            elegibles.append((len(semillas), ancla))
    elegibles.sort() #ordena primero por cantidad de semillas y luego por id 

    if len(elegibles) < 3 * n_por_bin:
        raise ValueError(f"solo {len(elegibles)} anclas elegibles, cuando hacen falta al menos "
                         f"{3 * n_por_bin}")

    asignacion = {}
    for nombre_bin, grupo in zip(BINS, np.array_split(np.arange(len(elegibles)), 3)):  #se generan los indicies 0,1,2,3.... y se parte eso en tres partes iguales. como la lista esta ordenada, los conjuntos seran de pocas semillas, de nivel medio y de nivel maximo
        for i in grupo:
            asignacion[elegibles[i][1]] = nombre_bin
    return asignacion


def intentar_bins(semillas_por_ancla, piso_semillas=MIN_SEMILLAS, n_por_bin=N_POR_BIN):
    """(asignacion, None) si la celda tiene pool, (None, motivo) si no lo tiene.

    Una celda flaca no deberia abortar el paso 0 entero: se registra el motivo, se saltea esa
    celda y las demas se sortean igual. Que celdas quedan afuera es un resultado del paso 0.
    """
    try:
        return bins_por_rango(semillas_por_ancla, piso_semillas, n_por_bin), None
    except ValueError as error:
        return None, str(error)


def bordes_de_bins(semillas_por_ancla, asignacion):
    """retorna {bin: (min, max)} de las semillas efectivas. Son los bordes que quedaron, es algo que va para el CSV."""
    bordes = {}
    for nombre_bin in BINS:
        tamanos = []
        for ancla, bin_del_ancla in asignacion.items():
            if bin_del_ancla == nombre_bin:
                tamanos.append(len(semillas_por_ancla[ancla]))
        bordes[nombre_bin] = (min(tamanos), max(tamanos)) if tamanos else (np.nan, np.nan)
    return bordes


def seleccionar_casos(semillas_por_ancla, asignacion, celda_nombre,
                      n_por_bin=N_POR_BIN, seed=SEED_SELECCION):
    """Sortea n_por_bin anclas por bin. de cada bin de una celda elige las 30 anclas que van a ser casos del experimento, y las devuelve como una tabla lista para escribir en casos.csv.
Por cada uno de los tres bins, arma la lista de candidatas filtrando la asignacion que produjo bins_por_rango
    
    """
    rng = np.random.default_rng([seed, *celda_nombre.encode()])
    filas = []
    for nombre_bin in BINS:
        candidatas = sorted(a for a, b in asignacion.items() if b == nombre_bin)
        if len(candidatas) < n_por_bin:
            raise ValueError(f"[{celda_nombre}] bin {nombre_bin}: {len(candidatas)} candidatas "
                             f"para {n_por_bin} lugares")
        for ancla in rng.choice(candidatas, size=n_por_bin, replace=False):
            filas.append({"celda": celda_nombre, "ancla": ancla,
                          "n_semillas": len(semillas_por_ancla[ancla]),
                          "bin": nombre_bin, "seed": seed})
    return pd.DataFrame(filas)


def grafico_ccdf_planos(grados_por_plano, pdf):
    """Grilla 2x2, un panel por plano: la CCDF de grado de la red donde corre DIAMOnD."""
    if list(grados_por_plano) != list(PLANOS):
        raise ValueError(f"la grilla espera exactamente {list(PLANOS)} y llegó "
                         f"{list(grados_por_plano)}")
    fig, ejes = plt.subplots(1, 2, figsize=(11, 4.5))
    for eje, (nombre, grados) in zip(ejes.flat, grados_por_plano.items()):
        x, y = ccdf(grados)
        eje.loglog(x, y, marker=".", linestyle="none", markersize=3)
        eje.set_title(f"plano {nombre} ({PLANOS[nombre].relacion})", fontsize=10)
        eje.set_xlabel("grado k")
        eje.set_ylabel("P(K >= k)")
    fig.suptitle("CCDF de grado de cada plano homogéneo (log-log)")
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def grados_bipartitos(gds, celda):
    """{label: [grados]} para los dos tipos de nodo de la capa bipartita de la celda.

    El grado de un nodo en la bipartita es su cantidad de vecinos del otro tipo, contados sobre
    los pares que devuelve la cosecha: los del origen son las semillas por ancla y los del destino
    son las anclas por semilla.
    """
    pares = cosechar(gds, celda)
    return {
        celda.origen: pares.groupby("ancla")["semilla"].nunique().tolist(),
        celda.tipo_destino: pares.groupby("semilla")["ancla"].nunique().tolist(),
    }


def grafico_ccdf_capas(grados_por_capa, pdf):
    """Grilla 2x3, un panel por capa bipartita y una CCDF por tipo de nodo del panel."""
    if list(grados_por_capa) != list(CAPAS_BIPARTITAS):
        raise ValueError(f"la grilla espera exactamente {list(CAPAS_BIPARTITAS)} y llegó "
                         f"{list(grados_por_capa)}")
    fig, ejes = plt.subplots(1, 1, figsize=(6, 4.5), squeeze=False)
    for eje, (nombre, por_label) in zip(ejes.flat, grados_por_capa.items()):
        for label, grados in por_label.items():
            x, y = ccdf(grados)
            eje.loglog(x, y, marker=".", linestyle="none", markersize=3, label=label)
        eje.set_title(nombre)
        eje.set_xlabel("grado k")
        eje.set_ylabel("P(K >= k)")
        eje.legend(fontsize=8)
    fig.suptitle("CCDF de grado por capa y tipo de nodo (log-log)")
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def main():
    os.makedirs(RESULTADOS, exist_ok=True)
    gds = conectar()
    grados_por_capa = {}
    for nombre_capa, nombre_celda in CAPAS_BIPARTITAS.items():
        grados_por_capa[nombre_capa] = grados_bipartitos(gds, CELDAS[nombre_celda])

    grados_por_plano = {}
    filas_celdas = []
    casos = []
    sin_control = []
    sin_pool = []

    for nombre_plano, plano in PLANOS.items():
        red = obtener_plano(gds, plano)
        grados_por_plano[nombre_plano] = [red.grado(n) for n in red.nodes()]

        for nombre_celda in CELDAS_POR_PLANO[nombre_plano]:
            celda = CELDAS[nombre_celda]
            semillas = semillas_efectivas(gds, celda, red)

            #el control se sortea sobre la red de corrida, que en las celdas del mismo tipo no
            #tiene al ancla
            n_candidatos = red.number_of_nodes() - (1 if celda.ancla_en_la_red else 0)
            semillas, descartadas = con_control_construible(semillas, n_candidatos)
            for ancla, n in descartadas.items():
                sin_control.append({"celda": nombre_celda, "ancla": ancla, "n_semillas": n,
                                    "candidatos": n_candidatos})

            asignacion, motivo = intentar_bins(semillas)
            if asignacion is None:
                sin_pool.append({"celda": nombre_celda, "motivo": motivo})
                print(f"[{nombre_celda}] SIN POOL: {motivo}", flush=True)
                continue

            casos.append(seleccionar_casos(semillas, asignacion, nombre_celda))
            bordes = bordes_de_bins(semillas, asignacion)
            filas_celdas.append({
                "celda": nombre_celda, "origen": celda.origen, "plano": nombre_plano,
                "relacion_cosecha": celda.relacion_cosecha,
                "nodos_plano": red.number_of_nodes(), "aristas_plano": red.number_of_edges(),
                "anclas_candidatas": len(semillas), "anclas_elegibles": len(asignacion),
                "descartadas_sin_control": len(descartadas),
                "max_semillas_bajo": bordes["bajo"][1],
                "max_semillas_medio": bordes["medio"][1],
                "max_semillas_alto": bordes["alto"][1]})
            print(f"[{nombre_celda}] {len(asignacion)} elegibles, bordes de bin "
                  f"{bordes['bajo'][1]:.0f}/{bordes['medio'][1]:.0f}/{bordes['alto'][1]:.0f}"
                  f"{f', {len(descartadas)} sin control construible' if descartadas else ''}",
                  flush=True)

    with PdfPages(os.path.join(RESULTADOS, "paso0_distribuciones.pdf")) as pdf:
        grafico_ccdf_capas(grados_por_capa, pdf)
        grafico_ccdf_planos(grados_por_plano, pdf)

    pd.DataFrame(filas_celdas).to_csv(os.path.join(RESULTADOS, "paso0_celdas.csv"), index=False)
    #las columnas se fijan aunque las listas esten vacias: el archivo documenta que se miro
    pd.DataFrame(sin_control, columns=["celda", "ancla", "n_semillas", "candidatos"]).to_csv(
        os.path.join(RESULTADOS, "descartadas_sin_control.csv"), index=False)
    pd.DataFrame(sin_pool, columns=["celda", "motivo"]).to_csv(
        os.path.join(RESULTADOS, "celdas_sin_pool.csv"), index=False)

    if casos:
        pd.concat(casos).to_csv(os.path.join(RESULTADOS, "casos.csv"), index=False)
    total = sum(len(c) for c in casos)
    print(f"\npaso 0 listo: {total} casos en {len(filas_celdas)} de {len(ORDEN_CELDAS)} celdas "
          f"({len(sin_control)} anclas descartadas por no admitir control apareado)")
    if sin_pool:
        print(f"celdas sin pool: {', '.join(f['celda'] for f in sin_pool)}")


if __name__ == "__main__":
    main()
