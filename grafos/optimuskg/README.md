# OptimusKG

El grafo con el que arrancó el trabajo. Se dejó porque el plano homogéneo de drogas era muy disconexo. Luego se pasó a tomar una versión enriquecida de PrimeKG. 

Queda acá como registro de lo que se hizo sobre él:

- `loader/`: la carga de OptimusKG a Neo4j. Descarga los parquet publicados en Dataverse y los inserta por lotes.
- `preparacion_grafo/`: la separación de las enfermedades reales del resto de la capa `Disease`. Fueron mas que nada análisis exploratorios que se fueron haciendo para ir entendiendo cómo es optimusKG y si DIAMOnD podía ser un buen fit para el grafo. 

Los scripts esperan el `.env` de la raíz del repositorio y un Neo4j con OptimusKG cargado.
