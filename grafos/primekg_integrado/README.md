# PrimeKG integrado

El grafo sobre el que sigue el trabajo. 


## Cómo se carga

Con Docker andando y el `.env` de la raíz completo (claves `PRIMEKG_NEO4J_*`):

```bash
grafos/primekg_integrado/neo4j/crear_contenedor.sh     # una sola vez
python grafos/primekg_integrado/neo4j/cargar_grafo.py
python grafos/primekg_integrado/grafo_laboratorio/armar_grafo.py
python grafos/primekg_integrado/neo4j/cargar_grafo_laboratorio.py
```

`cargar_grafo.py` carga genes, enfermedades y pathways desde `datos/`. `armar_grafo.py` une ese grafo con la red de compuestos del laboratorio (`grafo_laboratorio/datos/`) y escribe el resultado en `grafo_laboratorio/grafo/`. `cargar_grafo_laboratorio.py` reemplaza la capa `Drug` por esos compuestos y al terminar compara Neo4j contra los CSV, conteo por conteo.

Después alcanza con `docker start neo4j-thesis`. La carga es idempotente.

`datos/` y `grafo_laboratorio/datos/` no se versionan: se piden al laboratorio. El ID mapping de UniProt que usa `armar_grafo.py` se baja con los comandos de `grafo_laboratorio/fuentes/`.

## Conteos

`conteo_capas.ipynb` cuenta nodos por capa y aristas entre cada par de capas. `metricas_grafo.ipynb` compara Neo4j contra los CSV de origen y mide los planos homogéneos.
