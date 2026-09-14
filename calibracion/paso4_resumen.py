"""La tabla final del experimento: una fila por (celda, bin), con descriptores de las curvas.

Sin columnas de test estadistico: la comparacion real contra control es visual (las bandas de los
graficos), y esta tabla solo la resume en numeros descriptivos.

Escribe resultados/resumen_celdas.csv y un PDF de una pagina con la tabla y su pie de glosas. El
pie se deriva de GLOSA_COLUMNAS, y hay un test que exige correspondencia exacta entre columnas y
glosas en las dos direcciones, para que la tabla nunca se publique con un rotulo vencido.
"""
import os

import numpy as np
import pandas as pd

from celdas import CELDAS, ORDEN_CELDAS, RESULTADOS
from corrida import PRESUPUESTO
from graficos import banda_control, cargar_casos_corridos, cargar_recalls, cargar_trazas, \
    curva_promedio
from recall import FRAC_CON_CONTROL

#toda columna de la tabla tiene su glosa aca, y solo las columnas de la tabla la tienen
GLOSA_COLUMNAS = {
    "celda": "el paso del algoritmo: desde que tipo se cosecha y en que plano se expande",
    "origen": "tipo del ancla, la entidad de la consulta",
    "plano": "la red homogénea donde corre DIAMOnD",
    "relacion_cosecha": "la relación por la que el ancla trae sus semillas",
    "bin": "tamaño del conjunto semilla (tercil por rango de semillas efectivas en la celda)",
    "casos": "anclas corridas en la celda",
    "n_semillas_mediana": "mediana de semillas efectivas de los casos de la celda",
    "iteraciones_alcanzadas_mediana": "mediana, entre las corridas reales del bin, de la última "
                                      "iteración en que DIAMOnD agregó un nodo. Menor que el "
                                      "presupuesto cuando la red se agota antes",
    "frac_semillas_lcc_inicial_real": "fracción de semillas en la LCC en la iteración 0, antes "
                                      "de que DIAMOnD agregue nada, media de las corridas "
                                      "reales. Es la conectividad del conjunto que la celda "
                                      "cosecha, y lo que la expansión recibe de arranque",
    "frac_semillas_lcc_final_real": "fracción de semillas en la LCC al agotar el presupuesto, "
                                    "media de las corridas reales",
    "frac_desconectadas_integradas": "de las semillas que en la iteración 0 estaban fuera de la "
                                     "LCC, qué fracción terminó adentro: (final menos inicial) "
                                     "dividido (1 menos inicial). Es lo que aporta la expansión, "
                                     "descontando lo que ya venía conectado. En el paper de "
                                     "DIAMOnD este número va entre el 30% y el 60%",
    "frac_semillas_lcc_final_apareado": "ídem para las semillas de control apareadas por clase de "
                                        "grado (media de la banda): lo que conecta un conjunto "
                                        "de nodos al azar con los mismos grados que las semillas",
    "fuera_de_clase_media": "fracción media de semillas de control que hubo que tomar de una "
                            "clase de grado vecina porque la propia se agotó. 0 = apareo dentro "
                            "de la clase para todas. Alta solo donde las semillas son hubs "
                            "(grado 512 o más) y el plano tiene pocos",
    "lcc_tam_final_real": "tamaño de la componente conexa mayor del módulo al agotar el "
                          "presupuesto, media de las corridas reales",
    "salida_de_banda": "primera iteración donde la curva real supera la banda del control "
                       "apareado (media más un desvío). Vacío = nunca sale",
    "recall_final_medio": "recall de semillas escondidas al agotar el presupuesto, media de "
                          "folds por casos",
    "recall_final_ic95": "semiancho del IC95 de ese recall, calculado entre las medias por "
                         "ancla",
    "recall_final_azar": "recall esperable por azar en el mismo rank, con universo = la componente "
                         "alcanzable desde las semillas visibles, sin ellas. En gene, disease y "
                         "phenotype esa componente es casi el plano entero, así que la línea "
                         "queda pegada al piso. En drug pasa lo contrario y tampoco informa: el "
                         "universo tiene una mediana de 12 nodos, más chico que el presupuesto, "
                         "así que la fracción se satura en 1 antes del rango del gráfico. Por eso "
                         "la línea se dibuja solo hasta donde el universo se agota",
    "recall_final_apareado": "el mismo recall final medido escondiendo el 30% de un conjunto de "
                             "semillas al azar del mismo grado que las reales. Es el control del "
                             "recall: lo que DIAMOnD recupera por el grado solo, sin coherencia "
                             "modular",
    "iteracion_meseta_recall": "primera iteración en que el recall medio del bin alcanza el 95% "
                               "de su valor final. Es el criterio de corte del paper, y el "
                               "número que la calibración de cada paso necesita",
}

#la meseta se declara donde la curva llega a esta fraccion de su valor final. No se pide igualdad
#porque la curva medida tiene ruido y nunca queda exactamente plana
FRACCION_DE_LA_MESETA = 0.95


def salida_de_banda(curva_real, media_ctrl, desvio_ctrl):
    """Primera iteracion donde la curva real queda por encima de media mas un desvio del control.

    NaN si nunca sale. Es un descriptor del grafico, no un test.
    """
    techo = (media_ctrl + desvio_ctrl).reindex(curva_real.index)
    afuera = curva_real > techo
    return int(afuera.idxmax()) if afuera.any() else np.nan


def recall_final_del_bin(recalls_del_bin, presupuesto=PRESUPUESTO):
    """(media, semiancho del IC95, azar) del recall en la iteracion del presupuesto. Se promedian primero los folds de cada ancla y el intervalo se calcula entre anclas, que son las observaciones independientes. Las curvas ya vienen arrastradas, asi que todo fold tiene esa iteracion."""
    final = recalls_del_bin[recalls_del_bin["rank"] == presupuesto]
    por_ancla = final.groupby("ancla")["recall"].mean()
    azar = (final["rank"] / final["n_universo"]).clip(upper=1).mean()
    if len(por_ancla) < 2:
        ic95 = np.nan
    else:
        ic95 = 1.96 * por_ancla.std() / np.sqrt(len(por_ancla))
    return float(por_ancla.mean()), float(ic95), float(azar)


def valor_inicial(curva):
    """El valor de la curva en la iteracion 0, o NaN si la traza no la tiene.

    Las trazas de la primera corrida arrancan en la iteracion 1, porque el estado de las semillas
    solas no se guardaba todavia. Se las lee igual, con las dos columnas que dependen de la
    iteracion 0 vacias, en vez de romper la tabla entera.
    """
    if 0 not in curva.index:
        return np.nan
    return float(curva.loc[0])


def frac_desconectadas_integradas(inicial, final):
    """De las semillas que arrancaron fuera de la LCC, que fraccion termino adentro.

    Es como el paper resume la ley de crecimiento en su Discusion, y es lo que hay que mirar
    cuando el conjunto semilla ya viene conectado: una celda que arranca en 0,9 y termina en 0,95
    integro la mitad de lo que le faltaba, no creció un 5%. Si no habia ninguna semilla suelta el
    numero no esta definido.
    """
    if np.isnan(inicial) or inicial >= 1:
        return np.nan
    return (final - inicial) / (1 - inicial)


def meseta_del_recall(recalls_del_bin, presupuesto=PRESUPUESTO,
                      fraccion=FRACCION_DE_LA_MESETA):
    """La primera iteracion en que el recall medio del bin llega a la meseta.

    Es el criterio de corte que propone el paper: como el recall no depende del grado de
    completitud del conjunto semilla, el punto donde su curva satura marca hasta donde vale la
    pena expandir. Se promedia primero por ancla, igual que en el resto de la tabla.
    """
    if recalls_del_bin.empty:
        return np.nan
    por_rank = (recalls_del_bin.groupby(["ancla", "rank"])["recall"].mean()
                .groupby("rank").mean())
    if por_rank.empty or presupuesto not in por_rank.index:
        return np.nan
    final = por_rank.loc[presupuesto]
    if final <= 0:
        return np.nan
    alcanzan = por_rank[por_rank >= fraccion * final]
    return int(alcanzan.index[0])


def tabla_resumen():
    """Una fila por (celda, bin) con los descriptores de sus curvas."""
    filas = []
    for celda_nombre in ORDEN_CELDAS:
        casos = cargar_casos_corridos(celda_nombre)
        if casos.empty:
            continue
        celda = CELDAS[celda_nombre]
        trazas = cargar_trazas(celda_nombre, casos)
        recalls = cargar_recalls(celda_nombre, casos)

        for nombre_bin, del_bin in trazas.groupby("bin"):
            reales = del_bin[del_bin["fuente"] == "real"]
            curva_real = curva_promedio(reales, "frac_semillas_lcc")
            apareadas = del_bin[del_bin["fuente"] == "apareado"]
            media_ap, desvio_ap = banda_control(apareadas, "frac_semillas_lcc")
            #una fila por corrida apareada (ancla, sorteo): la fraccion de sus semillas de control
            #que salio de una clase vecina. Vacio si la traza no la trae (corridas anteriores)
            por_corrida = apareadas.groupby(["ancla", "sorteo"]).first()
            if "semillas_fuera_de_clase" in por_corrida.columns and not por_corrida.empty:
                fuera_de_clase = float(
                    (por_corrida["semillas_fuera_de_clase"] / por_corrida["n_semillas"]).mean())
            else:
                fuera_de_clase = np.nan
            #el recall se resume sobre el nivel de remocion que ademas tiene control, para que
            #la columna sea comparable con la del nulo. Los otros dos niveles viven en el grafico
            del_bin_recall = recalls[recalls["bin"] == nombre_bin]
            recall_real = del_bin_recall[
                (del_bin_recall["fuente"] == "real")
                & (del_bin_recall["frac_escondida"] == FRAC_CON_CONTROL)]
            recall_nulo = del_bin_recall[del_bin_recall["fuente"] == "apareado"]
            recall_medio, recall_ic95, recall_azar = recall_final_del_bin(recall_real)
            recall_apareado = recall_final_del_bin(recall_nulo)[0]
            #la ultima iteracion real de cada corrida, antes del arrastre. La fila de la
            #iteracion 0 no cuenta: no hay nodo agregado, y una corrida que no agrego nada tiene
            #que quedar en 0 y no en la iteracion de esa fila
            sin_arrastre = reales[(~reales["arrastrada"]) & (reales["iteracion"] > 0)]

            filas.append({
                "celda": celda_nombre, "origen": celda.origen, "plano": celda.plano,
                "relacion_cosecha": celda.relacion_cosecha, "bin": nombre_bin,
                "casos": reales["ancla"].nunique(),
                "n_semillas_mediana": float(
                    reales.groupby("ancla")["n_semillas"].first().median()),
                "iteraciones_alcanzadas_mediana": float(
                    sin_arrastre.groupby("ancla")["iteracion"].max()
                    .reindex(reales["ancla"].unique(), fill_value=0).median()),
                "frac_semillas_lcc_inicial_real": round(valor_inicial(curva_real), 4),
                "frac_semillas_lcc_final_real": round(float(curva_real.iloc[-1]), 4),
                "frac_desconectadas_integradas": round(frac_desconectadas_integradas(
                    valor_inicial(curva_real), float(curva_real.iloc[-1])), 4),
                "frac_semillas_lcc_final_apareado": (
                    round(float(media_ap.iloc[-1]), 4) if not media_ap.empty else np.nan),
                "fuera_de_clase_media": round(fuera_de_clase, 4),
                "lcc_tam_final_real": round(float(
                    curva_promedio(reales, "lcc_tam").iloc[-1]), 1),
                "salida_de_banda": salida_de_banda(curva_real, media_ap, desvio_ap),
                "recall_final_medio": round(recall_medio, 4),
                "recall_final_ic95": round(recall_ic95, 4),
                "recall_final_azar": round(recall_azar, 4),
                "recall_final_apareado": round(recall_apareado, 4),
                "iteracion_meseta_recall": meseta_del_recall(recall_real),
            })
    return pd.DataFrame(filas)


def pdf_resumen(tabla, ruta):
    """La tabla en una pagina, con el pie derivado de las glosas."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, eje = plt.subplots(figsize=(16, 0.5 + 0.32 * len(tabla) + 0.16 * len(GLOSA_COLUMNAS)))
    eje.axis("off")
    tabla_dibujada = eje.table(cellText=tabla.astype(str).values, colLabels=list(tabla.columns),
                               loc="upper center", cellLoc="center")
    tabla_dibujada.auto_set_font_size(False)
    tabla_dibujada.set_fontsize(5.5)
    tabla_dibujada.scale(1, 1.25)
    #el pie se DERIVA de las glosas: no hay texto de columnas escrito a mano
    pie = "\n".join(f"{col}: {glosa}" for col, glosa in GLOSA_COLUMNAS.items())
    eje.text(0, -0.02, pie, transform=eje.transAxes, fontsize=6.5, va="top")
    fig.suptitle("Crecimiento de DIAMOnD por celda: tabla resumen", y=0.98)
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)


def main():
    tabla = tabla_resumen()
    if tabla.empty:
        print("sin casos corridos todavía")
        return
    faltantes = set(tabla.columns) ^ set(GLOSA_COLUMNAS)
    if faltantes:   #cinturon ademas del test: nunca publicar una tabla con glosas vencidas
        raise ValueError(f"columnas sin glosa o glosas sin columna: {faltantes}")
    tabla.to_csv(os.path.join(RESULTADOS, "resumen_celdas.csv"), index=False)
    pdf_resumen(tabla, os.path.join(RESULTADOS, "resumen_celdas.pdf"))
    print(tabla.to_string(index=False))
    print(f"\n-> {RESULTADOS}/resumen_celdas.csv y .pdf ({len(tabla)} filas)")


if __name__ == "__main__":
    main()
