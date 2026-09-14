"""Regenera paso0_distribuciones.pdf de una carpeta de resultados sin volver a sortear los casos. Existe porque paso0.py escribe tambien casos.csv, y en resultados_con_grupos ese archivo es el del primer batch a proposito (comparacion pareada): correr paso0 de nuevo lo pisaria. Uso: CRECIMIENTO_RESULTADOS=<carpeta> CRECIMIENTO_GRUPOS_BERT=<excluidos|incluidos> python regenerar_distribuciones.py"""
import os

from matplotlib.backends.backend_pdf import PdfPages

from celdas import CELDAS, PLANOS, RESULTADOS, conectar, obtener_plano
from paso0 import CAPAS_BIPARTITAS, grados_bipartitos, grafico_ccdf_capas, grafico_ccdf_planos


def main():
    gds = conectar()
    grados_por_capa = {capa: grados_bipartitos(gds, CELDAS[celda]) for capa, celda in CAPAS_BIPARTITAS.items()}
    grados_por_plano = {}
    for nombre, plano in PLANOS.items():
        red = obtener_plano(gds, plano, verbose=False)
        grados_por_plano[nombre] = [red.grado(n) for n in red.nodes()]
    with PdfPages(os.path.join(RESULTADOS, "paso0_distribuciones.pdf")) as pdf:
        grafico_ccdf_capas(grados_por_capa, pdf)
        grafico_ccdf_planos(grados_por_plano, pdf)
    print(f"-> {RESULTADOS}/paso0_distribuciones.pdf")


if __name__ == "__main__":
    main()
