# Calibración: cómo crece el módulo de DIAMOnD en cada plano homogéneo

El experimento que calibra el algoritmo: para cada celda (tipo de la entidad de la consulta, tipo del plano donde se expande) mide cómo crece el módulo de DIAMOnD iteración a iteración, contra dos nulos (semillas al azar uniformes y apareadas por grado) y con recall sobre semillas escondidas. Corre sobre PrimeKG integrado cargado en `neo4j-thesis` (ver `../grafos/primekg_integrado/`); la red compacta y el port de DIAMOnD se importan de `../expansion/`.

La descripción completa del protocolo (vocabulario, los nueve pasos, las métricas y los controles) está pendiente de pasar a este repositorio; por ahora la bitácora resume qué se mide.

## Alcance actual

- **Dos tipos, dos planos, dos celdas.** Solo `Disease` y `Gene`, y solo las celdas cruzadas: el experimento mide proyecciones entre capas, no dentro de una capa. Drogas y fenotipos quedan para cuando estén sus planos.

  | plano | relación | nodos con arista | aristas |
  |---|---|---|---|
  | gene | `PPI` (HIPPIE) | 13.894 | 110.051 |
  | disease | `DISEASE_DISEASE` (MONDO), sin grupos BERT | 5.318 | 7.836 |

  | celda | vecinos de la capa B por | corre en |
  |---|---|---|
  | disease_a_gene | `GDA` | gene |
  | gene_a_disease | `GDA` | disease |

- **Los grupos BERT quedan fuera de todo** (1.040 nodos `Disease` con `es_grupo_bert`, hubs artificiales que unen sinónimos): no son anclas, no son semillas, no están en el plano, y la estrella `DISEASE_BERT` no se usa. Consecuencia: los 4.977 CUIs que cuelgan de un grupo no tienen aristas en el plano disease. La variante con los grupos incluidos se corrió aparte para medir la diferencia (`resultados_con_grupos/`, `comparar_inclusion_bert.ipynb`).
- **Sin umbral de evidencia.** Las asociaciones gen-enfermedad son las curadas de DisGeNET y no traen score.
- `FORM_COMPLEX` (complejos de SIGNOR) no entra al plano gene, para conservar una sola relación por plano.

## Los archivos

`celdas.py` es el único módulo que habla con Neo4j: define los planos, las celdas y las consultas. `paso0.py` arma las distribuciones, los bins por rango y el sorteo de casos; `runner.py` corre cada caso (`corrida.py` es una corrida de DIAMOnD, `controles.py` los nulos, `recall.py` los folds); `iteracion0.py` mide la conectividad del conjunto semilla antes de expandir; `resumen.py`, `graficos.py`, `informe.py` y `verificar.py` producen la salida y la chequean. `comparacion.py` sirve al notebook de comparación entre variantes.

Los scripts `.sh` lanzan y cierran un batch (`correr_batch.sh`, `cerrar_corrida.sh`), corren la variante con grupos BERT (`correr_con_grupos.sh`) y mantienen la máquina despierta mientras haya runners (`inhibir_suspension.sh`). Toman el intérprete de la variable `PY` (por defecto `python`).

## Cómo se corre

Con `neo4j-thesis` levantado y desde esta carpeta:

1. `CRECIMIENTO_N_POR_BIN=50 python paso0.py`: distribuciones (`resultados/paso0_distribuciones.pdf`), tabla por celda (`paso0_celdas.csv`) y sorteo de casos (`casos.csv`, seed 42).
2. `python smoke.py` sobre un par de casos, para ver que la traza y el recall salen.
3. `./correr_batch.sh` y, cuando termina, `./cerrar_corrida.sh`, que deja `resultados/RESUMEN_corrida.txt`.

De cada corrida se versionan los resúmenes (CSV, PDF, `RESUMEN_corrida.txt`, `graficos/`) y no las trazas por caso ni los logs.

## Corridas

- `resultados/`: 300 casos (150 por celda), 50 anclas por bin, presupuesto 100, grupos BERT excluidos (2026-09-10). DIAMOnD le gana a los dos nulos en las dos celdas. La verificación tiene un solo chequeo en falla que no es un error de la corrida: `verificar.py` trae fijado de OptimusKG que en `gene_a_disease` la fracción inicial de semillas en la LCC tiene que superar 0,8, y acá da 0,34 porque el plano disease es otro. Ese umbral hay que revisarlo para este grafo.
- `resultados_con_grupos/`: la misma corrida con los grupos BERT en el plano de enfermedades (2026-09-11), con las mismas 150 anclas de `gene_a_disease` para comparar ancla contra ancla. `disease_a_gene` no cambia y se copió.
