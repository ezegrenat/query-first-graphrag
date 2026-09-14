# Calibración: cómo crece el módulo de DIAMOnD en cada plano homogéneo

Para cada celda (tipo de la entidad de la consulta, tipo del plano donde se expande), este experimento mide cómo crece el módulo de DIAMOnD iteración a iteración, contra los dos nulos , que son semillas al azar uniformes y apareadas por grado. También se mide recall sobre semillas escondidas (un 30%). Corre sobre PrimeKG integrado cargado en `neo4j-thesis` (ver `../grafos/primekg_integrado/`); la red compacta y el algoritmo de DIAMOnD se importan de `../expansion/`.



## Alcance actual

Solo `Disease` y `Gene` y solo proyecciones cruzadas. Eventualmente se incorporará una capa de drogas externa.


## Los archivos

Hay tres clases de archivo, y el nombre dice cuál es cada uno.

**Lo que define el experimento.** Módulos que no se corren solos: los importan los pasos.

| archivo | qué es |
|---|---|
| `celdas.py` | los planos, las celdas y las consultas. Notar que es  el único módulo que habla con Neo4j |
| `corrida.py` | una corrida de DIAMOnD dentro de un plano, con la fracción de semillas en la LCC iteración a iteración |
| `controles.py` | los dos nulos: semillas uniformes al azar y apareadas por clase de grado |
| `recall.py` | los folds que esconden una fracción de las semillas y miden cuántas recupera el módulo |
| `graficos.py` | las figuras por plano y las funciones que leen trazas y recalls, usadas por los pasos 4 a 7 |

**Los pasos, en el orden en que se corren.** El prefijo `paso_necimo` es ese orden.

| paso | archivo | qué hace | qué deja en `resultados/` |
|---|---|---|---|
| 0 | `paso0_sorteo.py` | distribuciones de vecinos, bins por rango y sorteo de las anclas | `paso0_celdas.csv`, `casos.csv`, `paso0_distribuciones.pdf` |
| 1 | `paso1_smoke.py` | un par de casos completos, para ver que la traza y el recall salen y estimar el costo del batch | nada que se conserve |
| 2 | `paso2_runner.py` | el batch: cada caso con su corrida real, sus controles y sus folds | `trazas/` y `recalls/` (un parquet por caso, no se versionan) |
| 3 | `paso3_iteracion0.py` | la conectividad del conjunto semilla antes de expandir | `iteracion0_celdas.csv`, `iteracion0_casos.csv` |
| 4 | `paso4_resumen.py` | la tabla final: una fila por (celda, bin) con descriptores de las curvas (semillas, iteraciones alcanzadas, fracción en la LCC y tambien recall) | `resumen_celdas.csv`, `resumen_celdas.pdf` |
| 5 | `paso5_conteo.py` | en cuántos casos de cada bin el control le gana a DIAMOnD, por nivel final y por área bajo la curva | `conteo_control.csv` |
| 6 | `paso6_informe.py` | portada más todos los PDF anteriores en uno solo | `informe_completo.pdf` |
| 7 | `paso7_verificar.py` | asserts sobre parquet, tablas y PDF de la corrida | `verificacion.log` |

## Cómo se corre

Con `neo4j-thesis` levantado y desde esta carpeta:

```bash
CRECIMIENTO_N_POR_BIN=50 python paso0_sorteo.py
python paso1_smoke.py
./correr_batch.sh
./cerrar_corrida.sh          # cuando no queden runners; corre los pasos 3 a 7
```

Cada paso se puede volver a correr suelto, por ejemplo `python paso4_resumen.py`, sobre una carpeta de resultados ya hecha. La carpeta se elige con `CRECIMIENTO_RESULTADOS` (por defecto `resultados`).

De cada corrida se versionan los resúmenes (casos.csv, las tablas CSV, `informe_completo.pdf` y `RESUMEN_corrida.txt`) y no las trazas por caso, los PDF intermedios que el informe ya contiene ni los logs.


