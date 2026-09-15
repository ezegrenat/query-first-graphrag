# OptimusKG

El grafo con el que arrancó el trabajo. Se dejó porque el plano homogéneo de drogas era muy disconexo. Luego se pasó a tomar una versión enriquecida de PrimeKG. 

Queda acá como registro de lo que se hizo sobre él:

- `loader/`: la carga de OptimusKG a Neo4j. Descarga los parquet publicados en Dataverse y los inserta por lotes.
- `preparacion_grafo/`: la separación de las enfermedades reales del resto de la capa `Disease`. Fueron mas que nada análisis exploratorios que se fueron haciendo para ir entendiendo cómo es optimusKG y si DIAMOnD podía ser un buen fit para el grafo. 

Los scripts esperan el `.env` de la raíz del repositorio y un Neo4j con OptimusKG cargado.

## Sobre el `EVIDENCE_SCORE`

Las aristas gen-enfermedad de OptimusKG traen un `EVIDENCE_SCORE` tomado de Open Targets. Según la [documentación de Open Targets](https://platform-docs.opentargets.org/associations), ese score es una suma armónica de las evidencias disponibles por fuente, pesadas por fuente (Europe PMC 0,2; Expression Atlas 0,2; IMPC 0,2; OTAR projects 0,5; Cancer Biomarkers 0,5; otras 1,0), y la propia documentación advierte que "association scores are a heuristic based on the availability of data" y que "should not be interpreted as a confidence score for the target-disease association": una enfermedad poco estudiada no produce scores altos aunque sus asociaciones sean buenas.

En resumen: filtrar por `EVIDENCE_SCORE >= 0.5` esperando que eso signifique "hay más evidencia a favor que en contra" sería un error. El score mide disponibilidad de datos, no confianza en la asociación. El conteo de qué fuente puebla cada arista está en `preparacion_grafo/procedencia_evidence_score.ipynb`.
