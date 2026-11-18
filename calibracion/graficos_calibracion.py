
import os

#este script no se conecta a Neo4j, pero planos_y_pasos pide la contrasena al importarse
os.environ.setdefault("PRIMEKG_NEO4J_PASSWORD", "sin_uso")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402

from celdas import RESULTADOS  # noqa: E402
from corrida import PRESUPUESTO  # noqa: E402
from planos_y_pasos import K_POR_PASO  # noqa: E402
from recall import FRAC_CON_CONTROL  # noqa: E402

FIGURAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figuras")
CURVAS = os.path.join(RESULTADOS, "curvas_medias.csv")
PASOS = ["disease_a_gene", "drug_a_gene", "gene_a_disease", "drug_a_disease", "disease_a_drug", "gene_a_drug"]
NOMBRE = {"disease_a_gene": "enfermedad a genes", "drug_a_gene": "droga a genes", "gene_a_disease": "gen a enfermedades",
          "drug_a_disease": "droga a enfermedades", "disease_a_drug": "enfermedad a drogas", "gene_a_drug": "gen a drogas"}
TERCILES = ["bajo", "medio", "alto"]
MEDIDAS = [("lcc", "real"), ("lcc", "apareado"), ("recall", "real"), ("recall", "apareado")]
COLOR_PLANO = {"gene": "#4C72B0", "disease": "#DD8452", "drug": "#55A868"}
ANCHO = 16 / 2.54


def curva_media(df, indice, valor, rango):
    """Una columna por corrida, completada hasta el final del rango con el ultimo valor, y su media."""
    corridas = df.pivot_table(index=indice, columns=["sorteo", "fold"] if "fold" in df else "sorteo", values=valor)
    return corridas.reindex(rango).ffill().mean(axis=1)


def curvas_de(caso):
    trazas = pd.read_parquet(os.path.join(RESULTADOS, "trazas", f"{caso.celda}__{caso.entidad}.parquet"))
    recalls = pd.read_parquet(os.path.join(RESULTADOS, "recalls", f"{caso.celda}__{caso.entidad}.parquet"))
    recalls = recalls[recalls.frac_escondida == FRAC_CON_CONTROL]
    curvas = {}
    for fuente in ("real", "apareado"):
        curvas[("lcc", fuente)] = curva_media(trazas[trazas.fuente == fuente], "iteracion", "frac_semillas_lcc",
                                              range(PRESUPUESTO + 1))
        curvas[("recall", fuente)] = curva_media(recalls[recalls.fuente == fuente], "rank", "recall",
                                                 range(1, PRESUPUESTO + 1))
    return curvas


def armar_curvas(casos):
    """curvas_medias.csv: una fila por (paso, tercil, medida, fuente, iteracion)."""
    por_caso = {(caso.celda, caso.entidad): curvas_de(caso) for caso in casos.itertuples()}
    filas = []
    for (celda, tercil), grupo in casos.groupby(["celda", "bin"]):
        for medida, fuente in MEDIDAS:
            media = pd.concat([por_caso[(celda, e)][(medida, fuente)] for e in grupo.entidad], axis=1).mean(axis=1)
            filas += [{"paso": celda, "tercil": tercil, "medida": medida, "fuente": fuente,
                       "iteracion": iteracion, "valor": valor} for iteracion, valor in media.items()]
    return pd.DataFrame(filas)


def tono(color, tercil):
    #el tercil alto lleva el color pleno y los otros dos se aclaran mezclando con blanco
    mezcla = {"bajo": 0.55, "medio": 0.3, "alto": 0.0}[tercil]
    return tuple(c + (1 - c) * mezcla for c in to_rgb(color))


def grilla(curvas, plano_de, medida, etiqueta_y):
    figura, ejes = plt.subplots(2, 3, figsize=(ANCHO, 0.62 * ANCHO), sharex=True, sharey=True)
    for eje, celda in zip(ejes.flat, PASOS):
        for tercil in TERCILES:
            real, control = curvas[(celda, tercil, medida, "real")], curvas[(celda, tercil, medida, "apareado")]
            eje.plot(real.index, real, color=tono(COLOR_PLANO[plano_de[celda]], tercil), linewidth=1.6,
                     label=f"real, tercil {tercil}")
            eje.plot(control.index, control, color=tono("#555555", tercil), linewidth=1, linestyle=":",
                     label=f"control apareado, tercil {tercil}")
        eje.axvline(K_POR_PASO[celda], color="black", linewidth=0.8, linestyle="--")
        eje.text(K_POR_PASO[celda] + 2, 0.97, f"$k$ = {K_POR_PASO[celda]}", fontsize=8, va="top")
        eje.set_title(NOMBRE[celda])
        eje.set_xlim(0, PRESUPUESTO)
        eje.set_ylim(0, 1)
        eje.grid(color="#EEEEEE", linewidth=0.6)
        eje.set_axisbelow(True)
    figura.supylabel(etiqueta_y)
    asas, etiquetas = ejes[0, 0].get_legend_handles_labels()
    figura.legend(asas, etiquetas, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.1))
    figura.tight_layout()
    return figura


def tabla_k(curvas):
    """k elegido contra la iteracion en que el recall medio del paso (los tres terciles) llega al 80 % del final."""
    filas = []
    for celda in PASOS:
        media = pd.concat([curvas[(celda, t, "recall", "real")] for t in TERCILES], axis=1).mean(axis=1)
        final = media.loc[PRESUPUESTO]
        k = K_POR_PASO[celda]
        filas.append({"paso": celda, "k": k,
                      "iteracion_80": int(media[media >= 0.8 * final].index[0]),
                      "iteracion_95": int(media[media >= 0.95 * final].index[0]),
                      "recall_en_k": round(media.loc[k], 3), "recall_final": round(final, 3),
                      "fraccion_conservada": round(media.loc[k] / final, 2)})
    return pd.DataFrame(filas)


def main():
    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9, "legend.fontsize": 8,
                         "xtick.labelsize": 8, "ytick.labelsize": 8, "figure.dpi": 110})
    plano_de = pd.read_csv(os.path.join(RESULTADOS, "paso0_celdas.csv")).set_index("celda").plano
    if os.path.isdir(os.path.join(RESULTADOS, "trazas")):
        casos = pd.read_csv(os.path.join(RESULTADOS, "casos.csv"))
        tabla = armar_curvas(casos)
        tabla.to_csv(CURVAS, index=False)
        print(f"{len(casos)} casos leidos, curvas en {CURVAS}")
    else:
        tabla = pd.read_csv(CURVAS)
        print(f"sin trazas/ en {RESULTADOS}: curvas leidas de {CURVAS}")
    curvas = {clave: grupo.set_index("iteracion").valor
              for clave, grupo in tabla.groupby(["paso", "tercil", "medida", "fuente"])}

    os.makedirs(FIGURAS, exist_ok=True)
    for medida, etiqueta, nombre in [("lcc", "fracción de semillas en la LCC", "calibracion_lcc"),
                                     ("recall", "recall de semillas escondidas", "calibracion_recall")]:
        figura = grilla(curvas, plano_de, medida, etiqueta)
        for extension in ("pdf", "png"):
            figura.savefig(os.path.join(FIGURAS, f"{nombre}.{extension}"), dpi=200, bbox_inches="tight")
        plt.close(figura)

    k = tabla_k(curvas)
    k.to_csv(os.path.join(RESULTADOS, "k_por_paso.csv"), index=False)
    print(k.to_string(index=False))


if __name__ == "__main__":
    main()
