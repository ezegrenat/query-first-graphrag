"""calcula en cuantos casos el control le gana a DIAMOnD, celda por celda.

Resume la comparacion real contra control caso por caso en vez de por el promedio del bin. Cada ancla se compara contra el promedio de sus propios controles (uniformes, y apareados por clase de grado), y se cuenta en cuantas de las del bin el control queda por encima.

Se reportan dos criterios porque responden preguntas distintas:

- **final**: quien queda mas alto al agotar el presupuesto
- **area**: quien acumula mas area bajo la curva a lo largo de todo el recorrido. Premia llegar antes

Salida: resultados/conteo_control.csv y la tabla por consola.
"""
import os

import pandas as pd

from celdas import CELDAS, ORDEN_CELDAS, RESULTADOS
from graficos import cargar_casos_corridos, cargar_trazas, nulo_gana
from paso0_sorteo import BINS

COLUMNA = "frac_semillas_lcc"


def _final_por_ancla(del_bin, fuente):
    """{ancla: valor en la ultima iteracion}, promediando los sorteos de la fuente."""
    de_la_fuente = del_bin[del_bin["fuente"] == fuente]
    #primero se promedia dentro de cada corrida (ancla, sorteo), despues entre sorteos
    por_corrida = de_la_fuente.groupby(["ancla", "sorteo", "iteracion"])[COLUMNA].mean()
    return por_corrida.unstack("iteracion").iloc[:, -1].groupby(level="ancla").mean()


def conteos():
    """Una fila por (celda, bin) con los dos criterios de conteo.

    Los nulos son el uniforme y el apareado por clase de grado. Las columnas del apareado solo
    aparecen si la traza lo trae, asi que la corrida 2 (que tenia reordenado en su lugar) se lee
    sin romper, con el uniforme solo.
    """
    filas = []
    for celda_nombre in ORDEN_CELDAS:
        casos = cargar_casos_corridos(celda_nombre)
        if casos.empty:
            continue
        celda = CELDAS[celda_nombre]
        trazas = cargar_trazas(celda_nombre, casos)
        for nombre_bin in BINS:
            del_bin = trazas[trazas["bin"] == nombre_bin]
            if del_bin.empty:
                continue
            #el criterio por area es el mismo que anotan los graficos: una sola implementacion
            area = nulo_gana(del_bin, COLUMNA)
            real_final = _final_por_ancla(del_bin, "real")
            uniforme_final = _final_por_ancla(del_bin, "uniforme")
            comunes_u = real_final.index.intersection(uniforme_final.index)
            fila = {
                "celda": celda_nombre, "origen": celda.origen, "plano": celda.plano,
                "relacion_cosecha": celda.relacion_cosecha, "bin": nombre_bin,
                "casos": area["casos"],
                "gana_uniforme_area": area["uniforme"],
                "gana_uniforme_final": int(
                    (uniforme_final[comunes_u] >= real_final[comunes_u]).sum()),
            }
            for fuente in ("apareado",):
                if fuente not in area:
                    continue
                final_de_la_fuente = _final_por_ancla(del_bin, fuente)
                comunes_f = real_final.index.intersection(final_de_la_fuente.index)
                fila[f"gana_{fuente}_area"] = area[fuente]
                fila[f"gana_{fuente}_final"] = int(
                    (final_de_la_fuente[comunes_f] >= real_final[comunes_f]).sum())
            filas.append(fila)
    return pd.DataFrame(filas)


def main():
    tabla = conteos()
    if tabla.empty:
        print("sin casos corridos todavía")
        return
    tabla.to_csv(os.path.join(RESULTADOS, "conteo_control.csv"), index=False)
    print("En cuántos casos el CONTROL le gana a DIAMOnD (de los casos de cada celda)\n")
    for plano, del_plano in tabla.groupby("plano", sort=False):
        print(f"plano {plano}")
        for celda_nombre, del_celda in del_plano.groupby("celda", sort=False):
            print(f"  {celda_nombre}")
            for _, fila in del_celda.iterrows():
                partes = [f"     bin {fila['bin']:5s} n={fila['casos']:3d}"]
                for fuente in ("apareado", "uniforme"):
                    if f"gana_{fuente}_area" not in fila or pd.isna(fila[f"gana_{fuente}_area"]):
                        continue
                    partes.append(f"{fuente} gana en {fila[f'gana_{fuente}_area']:.0f} por área, "
                                  f"{fila[f'gana_{fuente}_final']:.0f} por valor final")
                print(" | ".join(partes))
    print(f"\n-> {RESULTADOS}/conteo_control.csv ({len(tabla)} filas)")


if __name__ == "__main__":
    main()
