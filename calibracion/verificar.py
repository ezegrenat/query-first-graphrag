"""Verificacion de una corrida: comprueba con asserts que los parquet, las tablas y los PDF de un directorio de resultados tienen la forma que el diseño vigente declara, antes de dar por buena la corrida y antes de gastar la noche del batch. Se corre con CRECIMIENTO_RESULTADOS apuntando al directorio a verificar (celdas.py lo lee al importar), por ejemplo CRECIMIENTO_RESULTADOS=resultados_verificacion python verificar.py. Imprime una linea por chequeo y termina con codigo 1 si alguno fallo. Los chequeos son los de la fase 2 de DIAGNOSTICO_metricas_y_plan.md ajustados al diseño del 2026-09-05: sin p valor, nulos uniforme y apareado por clase de grado, recall en tres niveles con control sobre los conjuntos apareados."""
import os
import sys

import numpy as np
import pandas as pd

from celdas import CELDAS, ORDEN_CELDAS, RESULTADOS
from controles import N_SORTEOS, N_SORTEOS_RECALL
from corrida import PRESUPUESTO
from graficos import DIR_GRAFICOS, cargar_casos_corridos, cargar_recalls, cargar_trazas
from recall import FRAC_CON_CONTROL, FRACCIONES_ESCONDIDAS, N_FOLDS
from runner import DIR_RECALLS, DIR_TRAZAS, _ruta

#los ordenes de magnitud medidos en la corrida 1 que una corrida nueva tiene que reproducir: en
#gene_a_disease las semillas ya vienen conectadas (fraccion inicial real alta) y un conjunto de
#nodos al azar del mismo grado en la taxonomia casi nunca comparte rama (fraccion inicial del
#apareado baja). En gene_a_drug la red se agota y la fraccion final queda cerca de 0,1, no de
#0,015 como daba el bug de agregacion de la corrida 1
INICIAL_REAL_MINIMA_GENE_A_DISEASE = 0.8
INICIAL_APAREADO_MAXIMA_GENE_A_DISEASE = 0.3
FINAL_GENE_A_DRUG = (0.03, 0.3)

fallas = []


def chequear(condicion, mensaje):
    """Imprime el resultado de un chequeo y acumula la falla si no se cumple."""
    print(f"  {'ok   ' if condicion else 'FALLA'} {mensaje}")
    if not condicion:
        fallas.append(mensaje)


def verificar_parquet_crudos(casos_por_celda):
    """La forma de cada parquet tal como lo escribio el runner, antes de cualquier carga."""
    print("\nparquet crudos")
    corridas_esperadas = 1 + 2 * N_SORTEOS
    folds_reales = N_FOLDS * len(FRACCIONES_ESCONDIDAS)
    folds_nulo = N_FOLDS * N_SORTEOS_RECALL
    sin_fila_0, sin_log10p, corridas_mal, fuentes_mal = 0, 0, 0, 0
    recalls_mal, niveles_mal, total, sin_columnas, sin_fuera_de_clase = 0, 0, 0, 0, 0
    #cuantos casos por plano tienen alguna semilla de control fuera de su clase. No es un chequeo
    #sino informacion: pasa donde las clases altas tienen uno o pocos nodos (las taxonomias), y
    #suponer que no pasaba en drug y phenotype fue un error de la primera version de este script
    casos_con_fuera_de_clase = {}
    for celda_nombre, casos in casos_por_celda.items():
        celda = CELDAS[celda_nombre]
        for ancla in casos["ancla"]:
            total += 1
            traza = pd.read_parquet(_ruta(DIR_TRAZAS, celda, ancla))
            curvas = pd.read_parquet(_ruta(DIR_RECALLS, celda, ancla))
            #una corrida vieja no trae estas columnas. Se cuenta y se sigue, en vez de reventar
            #con un KeyError: el mensaje tiene que decir que el parquet es de otro formato
            if "fuente" not in traza.columns or "fuente" not in curvas.columns:
                sin_columnas += 1
                continue
            if "log10_p" in traza.columns:
                sin_log10p += 1
            if set(traza["fuente"]) != {"real", "uniforme", "apareado"}:
                fuentes_mal += 1
            por_corrida = traza.groupby(["fuente", "sorteo"])["iteracion"].min()
            if len(por_corrida) != corridas_esperadas:
                corridas_mal += 1
            if (por_corrida != 0).any():
                sin_fila_0 += 1
            apareadas = traza[traza["fuente"] == "apareado"]
            if "semillas_fuera_de_clase" not in traza.columns or apareadas["semillas_fuera_de_clase"].isna().any():
                sin_fuera_de_clase += 1
            elif (apareadas["semillas_fuera_de_clase"] > 0).any():
                casos_con_fuera_de_clase[celda.plano] = casos_con_fuera_de_clase.get(celda.plano, 0) + 1
            reales = curvas[curvas["fuente"] == "real"].groupby(["frac_escondida", "fold"]).size()
            nulos = curvas[curvas["fuente"] == "apareado"].groupby(["sorteo", "fold"]).size()
            #un fold sin filas (DIAMOnD no agrego nada) es legitimo y lo completa la carga, asi
            #que aca solo se exige que no sobren folds ni niveles
            if len(reales) > folds_reales or len(nulos) > folds_nulo:
                recalls_mal += 1
            niveles = set(curvas["frac_escondida"].round(2))
            if not niveles <= set(round(f, 2) for f in FRACCIONES_ESCONDIDAS):
                niveles_mal += 1
            if not set(curvas.loc[curvas["fuente"] == "apareado", "frac_escondida"].round(2)) <= {round(FRAC_CON_CONTROL, 2)}:
                niveles_mal += 1
    chequear(total > 0, f"{total} casos con sus dos parquet")
    chequear(sin_columnas == 0,
             f"todos los parquet tienen la columna fuente ({sin_columnas} son de una corrida "
             f"anterior al recall con control y no se pueden verificar)")
    chequear(sin_log10p == 0, f"ninguna traza trae log10_p ({sin_log10p} lo traen)")
    chequear(fuentes_mal == 0, f"toda traza tiene exactamente las fuentes real, uniforme y apareado ({fuentes_mal} no)")
    chequear(corridas_mal == 0, f"toda traza tiene {corridas_esperadas} corridas ({corridas_mal} no)")
    chequear(sin_fila_0 == 0, f"toda corrida arranca en la iteracion 0 ({sin_fila_0} no)")
    chequear(sin_fuera_de_clase == 0, f"toda corrida apareada registra semillas_fuera_de_clase ({sin_fuera_de_clase} casos no)")
    print(f"  info  casos con alguna semilla de control fuera de su clase, por plano: {casos_con_fuera_de_clase or 'ninguno'}")
    chequear(recalls_mal == 0, f"a lo sumo {folds_reales} folds reales y {folds_nulo} del nulo por caso ({recalls_mal} casos con mas)")
    chequear(niveles_mal == 0, f"niveles de remocion {FRACCIONES_ESCONDIDAS} y el nulo solo en {FRAC_CON_CONTROL} ({niveles_mal} casos mal)")


def verificar_carga(casos_por_celda):
    """Lo que devuelven cargar_trazas y cargar_recalls: arrastre completo, sin NaN donde no debe haber, y los ordenes de magnitud conocidos."""
    print("\ncarga y arrastre")
    nan_final, cortas, arrastradas_con_nodo, folds_cortos = 0, 0, 0, 0
    inicial_real_gad, inicial_ap_gad, final_gadrug = np.nan, np.nan, np.nan
    for celda_nombre, casos in casos_por_celda.items():
        trazas = cargar_trazas(celda_nombre, casos)
        por_corrida = trazas.groupby(["ancla", "fuente", "sorteo"])["iteracion"].agg(["min", "max", "size"])
        cortas += int(((por_corrida["max"] != PRESUPUESTO) | (por_corrida["size"] != PRESUPUESTO + 1)).sum())
        en_100 = trazas[trazas["iteracion"] == PRESUPUESTO]
        nan_final += int(en_100[["frac_semillas_lcc", "lcc_tam"]].isna().any(axis=1).sum())
        arrastradas = trazas[trazas["arrastrada"]]
        arrastradas_con_nodo += int(arrastradas[["grado", "kb"]].notna().any(axis=1).sum())
        recalls = cargar_recalls(celda_nombre, casos)
        por_fold = recalls.groupby(["ancla", "fuente", "sorteo", "frac_escondida", "fold"])["rank"].agg(["max", "size"])
        folds_cortos += int(((por_fold["max"] != PRESUPUESTO) | (por_fold["size"] != PRESUPUESTO)).sum())
        if celda_nombre == "gene_a_disease":
            en_0 = trazas[trazas["iteracion"] == 0]
            inicial_real_gad = en_0.loc[en_0["fuente"] == "real", "frac_semillas_lcc"].mean()
            inicial_ap_gad = en_0.loc[en_0["fuente"] == "apareado", "frac_semillas_lcc"].mean()
        if celda_nombre == "gene_a_drug":
            final_gadrug = en_100.loc[en_100["fuente"] == "real", "frac_semillas_lcc"].mean()
    chequear(cortas == 0, f"toda corrida cargada va de la iteracion 0 a la {PRESUPUESTO} ({cortas} no)")
    chequear(nan_final == 0, f"sin NaN en frac_semillas_lcc ni lcc_tam en la iteracion {PRESUPUESTO} ({nan_final} filas con NaN)")
    chequear(arrastradas_con_nodo == 0, f"las filas arrastradas no describen ningun nodo ({arrastradas_con_nodo} lo hacen)")
    chequear(folds_cortos == 0, f"todo fold cargado tiene los {PRESUPUESTO} ranks ({folds_cortos} no)")
    if "gene_a_disease" in casos_por_celda:
        chequear(inicial_real_gad > INICIAL_REAL_MINIMA_GENE_A_DISEASE,
                 f"gene_a_disease: fraccion inicial real {inicial_real_gad:.2f} > {INICIAL_REAL_MINIMA_GENE_A_DISEASE}")
        chequear(inicial_ap_gad < INICIAL_APAREADO_MAXIMA_GENE_A_DISEASE,
                 f"gene_a_disease: fraccion inicial del apareado {inicial_ap_gad:.2f} < {INICIAL_APAREADO_MAXIMA_GENE_A_DISEASE}")
    if "gene_a_drug" in casos_por_celda:
        chequear(FINAL_GENE_A_DRUG[0] <= final_gadrug <= FINAL_GENE_A_DRUG[1],
                 f"gene_a_drug: fraccion final real {final_gadrug:.3f} en {FINAL_GENE_A_DRUG}")


def verificar_resumen():
    """La tabla resumen y sus glosas, si ya se corrio resumen.py sobre este directorio."""
    print("\ntabla resumen")
    ruta = os.path.join(RESULTADOS, "resumen_celdas.csv")
    if not os.path.exists(ruta):
        chequear(False, f"falta {ruta}: correr resumen.py")
        return
    from resumen import GLOSA_COLUMNAS
    tabla = pd.read_csv(ruta)
    chequear(set(tabla.columns) == set(GLOSA_COLUMNAS), "las columnas de la tabla son exactamente las que tienen glosa")
    nuevas = ["frac_semillas_lcc_inicial_real", "frac_semillas_lcc_final_apareado", "salida_de_banda",
              "recall_final_apareado", "iteracion_meseta_recall", "frac_desconectadas_integradas",
              "fuera_de_clase_media"]
    faltantes = [c for c in nuevas if c not in tabla.columns]
    if faltantes:
        #tabla de una corrida anterior a estas columnas: se avisa y no se chequea el contenido,
        #en vez de cortar con un KeyError
        chequear(False, f"la tabla no tiene las columnas {faltantes}: es de una corrida anterior")
        return
    #salida_de_banda es NaN a proposito cuando la curva real nunca sale de la banda, asi que se
    #exige que no sea NaN en todas las filas, no en cada una. La meseta es NaN a proposito cuando
    #el recall final del bin es 0 (no hay curva que sature), asi que solo se exige donde hay recall
    for columna in nuevas:
        if columna == "salida_de_banda":
            chequear(tabla[columna].notna().any(), f"{columna}: al menos una fila con valor")
        elif columna == "frac_desconectadas_integradas":
            continue
        elif columna == "iteracion_meseta_recall":
            con_recall = tabla[tabla["recall_final_medio"] > 0]
            chequear(con_recall[columna].notna().all(),
                     f"{columna}: sin NaN donde el recall final es mayor que 0 "
                     f"({int(con_recall[columna].isna().sum())} NaN, {int((tabla['recall_final_medio'] <= 0).sum())} filas con recall 0)")
        else:
            chequear(tabla[columna].notna().all(), f"{columna}: sin NaN ({int(tabla[columna].isna().sum())} NaN)")
    meseta = tabla["iteracion_meseta_recall"].dropna()
    chequear(((meseta >= 1) & (meseta <= PRESUPUESTO)).all(), f"iteracion_meseta_recall entre 1 y {PRESUPUESTO}")
    fuera = tabla["fuera_de_clase_media"]
    chequear(((fuera >= 0) & (fuera <= 1)).all(), "fuera_de_clase_media entre 0 y 1")
    por_plano = tabla.groupby("plano")["fuera_de_clase_media"].max().round(3).to_dict()
    print(f"  info  fuera_de_clase_media maxima por plano: {por_plano}")
    conectadas = tabla[tabla["frac_semillas_lcc_inicial_real"] >= 1]
    chequear(conectadas["frac_desconectadas_integradas"].isna().all(),
             f"frac_desconectadas_integradas es NaN donde la fraccion inicial ya es 1 ({len(conectadas)} filas)")


#paginas que graficos.py escribe por plano: iteracion 0, ley de crecimiento, distribucion por
#iteracion, recall contra el nulo, recall en los tres niveles, y tamaño de la componente
PAGINAS_POR_PLANO = 4


def verificar_pdf():
    """Seis paginas por plano, si ya se corrio graficos.py sobre este directorio."""
    print("\ngraficos")
    from pypdf import PdfReader
    encontrados = 0
    for archivo in sorted(os.listdir(DIR_GRAFICOS)) if os.path.isdir(DIR_GRAFICOS) else []:
        if archivo.endswith(".pdf"):
            encontrados += 1
            paginas = len(PdfReader(os.path.join(DIR_GRAFICOS, archivo)).pages)
            chequear(paginas == PAGINAS_POR_PLANO,
                     f"{archivo}: {paginas} paginas (se esperan {PAGINAS_POR_PLANO})")
    chequear(encontrados > 0, f"{encontrados} PDF de planos en {DIR_GRAFICOS}")


def main():
    print(f"verificando {RESULTADOS}")
    casos_por_celda = {}
    for celda_nombre in ORDEN_CELDAS:
        casos = cargar_casos_corridos(celda_nombre)
        if not casos.empty:
            casos_por_celda[celda_nombre] = casos
    print(f"  celdas con casos corridos: {len(casos_por_celda)} de {len(ORDEN_CELDAS)}")
    verificar_parquet_crudos(casos_por_celda)
    verificar_carga(casos_por_celda)
    verificar_resumen()
    verificar_pdf()
    print()
    if fallas:
        print(f"{len(fallas)} chequeos fallaron:")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("todos los chequeos pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
