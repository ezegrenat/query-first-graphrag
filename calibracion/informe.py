"""El informe completo del experimento en un solo PDF.

Junta, en este orden: una portada con que se corrio, las distribuciones del paso 0, las cuatro
paginas de cada plano (leyendo plano por plano, con sus metricas juntas) y la tabla resumen.

No recalcula nada: toma los PDF que ya escribieron paso0.py, graficos.py y resumen.py, de modo
que el informe y los archivos sueltos no pueden discrepar. Los PDF por plano se siguen
escribiendo aparte porque las diapositivas los incluyen de a uno, y porque mirar un solo plano no
deberia pedir abrir el documento entero.
"""
import os
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

from celdas import CELDAS, ORDEN_CELDAS, PLANOS, RESULTADOS  # noqa: E402
from controles import N_SORTEOS, N_SORTEOS_RECALL  # noqa: E402
from corrida import PRESUPUESTO  # noqa: E402
from graficos import DIR_GRAFICOS, cargar_casos_corridos  # noqa: E402
from paso0 import N_POR_BIN, SEED_SELECCION  # noqa: E402
from recall import FRAC_ESCONDIDA, N_FOLDS  # noqa: E402

RUTA_INFORME = os.path.join(RESULTADOS, "informe_completo.pdf")


def casos_por_celda():
    """{celda: casos corridos} segun lo que hay en disco, no segun lo que se sorteo."""
    return {celda: len(cargar_casos_corridos(celda)) for celda in ORDEN_CELDAS}


def portada(ruta):
    """Una pagina con lo que hace falta para leer el resto sin buscar en el codigo."""
    corridos = casos_por_celda()

    lineas = [
        "Qué se corrió",
        "",
        "Una celda es un paso del algoritmo: dada un ancla de tipo A, se cosechan sus vecinos",
        "de tipo B y se corre DIAMOnD dentro del plano B-B, la red que forman los nodos de",
        "tipo B entre sí. El salto entre tipos lo hace la cosecha, DIAMOnD nunca cambia de tipo.",
        "",
        f"Con dos tipos hay {len(ORDEN_CELDAS)} celdas repartidas en {len(PLANOS)} planos.",
        f"Por celda, {N_POR_BIN} anclas por bin de tamaño del conjunto semilla (bins por rango",
        "de semillas efectivas en el plano).",
        "",
        f"Por caso: una corrida real de {PRESUPUESTO} iteraciones, {N_SORTEOS} controles "
        f"uniformes, {N_SORTEOS} controles con semillas apareadas por clase de grado (grado "
        f"exacto hasta 7, potencias de 2 desde 8, una sola clase de hubs desde 512), y "
        f"{N_FOLDS} folds de recall por cada nivel de remoción (10%, 20% y {FRAC_ESCONDIDA:.0%}), "
        f"más los folds del nulo sobre los primeros {N_SORTEOS_RECALL} conjuntos apareados en el "
        f"nivel del {FRAC_ESCONDIDA:.0%}.",
        "",
        "El ancla se excluye de la red solo en las cuatro celdas del mismo tipo, que son las",
        "únicas donde pertenece al plano. En las cruzadas es de otro tipo y no está. Los nodos",
        "genéricos de la taxonomía no se excluyen.",
        "",
        "La comparación real contra control es visual: la banda es la media más o menos un",
        f"desvío sobre los {N_SORTEOS} sorteos.",
        "",
        "Los planos donde corre DIAMOnD",
        "",
    ]
    for nombre, plano in PLANOS.items():
        filtro = f", filtrado por {plano.filtro_cypher}" if plano.filtro_cypher else ""
        lineas.append(f"    {nombre:12s} {plano.tipo}-{plano.tipo} vía {plano.relacion}{filtro}")

    lineas += [
        "",
        "Sin umbral de evidencia: las asociaciones gen-enfermedad son las curadas de DisGeNET",
        "que trae PrimeKG integrado y no tienen score. Los grupos BERT quedan fuera de todo.",
        "",
        f"Seed de todos los sorteos: {SEED_SELECCION}",
        "",
        "Casos corridos por celda",
        "",
    ]
    for celda_nombre in ORDEN_CELDAS:
        celda = CELDAS[celda_nombre]
        lineas.append(f"    {celda_nombre:24s} ancla {celda.origen:10s} plano "
                      f"{celda.plano:10s} {corridos.get(celda_nombre, 0):4d} casos")

    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.06, 0.95, "Crecimiento de DIAMOnD por celda de proyección",
             fontsize=15, weight="bold", va="top")
    fig.text(0.06, 0.92, f"OptimusKG en Neo4j. Informe generado el {date.today().isoformat()}",
             fontsize=9, color="#555555", va="top")
    fig.text(0.06, 0.885, "\n".join(lineas), fontsize=7.5, family="monospace", va="top")
    fig.savefig(ruta)
    plt.close(fig)


def paginas_del_informe():
    """Las rutas a concatenar, en orden, salteando lo que todavia no exista."""
    rutas = [os.path.join(RESULTADOS, "paso0_distribuciones.pdf")]
    for plano_nombre in PLANOS:
        rutas.append(os.path.join(DIR_GRAFICOS, f"{plano_nombre}.pdf"))
    rutas.append(os.path.join(RESULTADOS, "resumen_celdas.pdf"))
    return [r for r in rutas if os.path.exists(r)]


def indice_de_planos(escritor, paginas_previas):
    """Marcadores por plano, para poder saltar dentro del PDF sin contar paginas."""
    pagina = paginas_previas
    for plano_nombre, plano in PLANOS.items():
        ruta = os.path.join(DIR_GRAFICOS, f"{plano_nombre}.pdf")
        if not os.path.exists(ruta):
            continue
        escritor.add_outline_item(f"plano {plano_nombre} ({plano.relacion})", pagina)
        pagina += len(PdfReader(ruta).pages)
    return pagina


def main():
    ruta_portada = os.path.join(RESULTADOS, "_portada.pdf")
    portada(ruta_portada)

    escritor = PdfWriter()
    for pagina in PdfReader(ruta_portada).pages:
        escritor.add_page(pagina)
    escritor.add_outline_item("Portada", 0)

    #el paso 0 va antes de los planos, el indice se arma sobre las paginas ya contadas
    ruta_paso0 = os.path.join(RESULTADOS, "paso0_distribuciones.pdf")
    previas = len(escritor.pages)
    if os.path.exists(ruta_paso0):
        escritor.add_outline_item("Distribuciones (paso 0)", previas)
        previas += len(PdfReader(ruta_paso0).pages)

    for ruta in paginas_del_informe():
        for pagina in PdfReader(ruta).pages:
            escritor.add_page(pagina)
    ultima = indice_de_planos(escritor, previas)
    if os.path.exists(os.path.join(RESULTADOS, "resumen_celdas.pdf")):
        escritor.add_outline_item("Tabla resumen", min(ultima, len(escritor.pages) - 1))

    with open(RUTA_INFORME, "wb") as f:
        escritor.write(f)
    os.remove(ruta_portada)
    print(f"-> {RUTA_INFORME} ({len(escritor.pages)} páginas)")


if __name__ == "__main__":
    main()
