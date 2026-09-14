# PrimeKG integrado

El grafo sobre el que sigue el trabajo. 


## Cómo se carga

Con Docker andando y el `.env` de la raíz completo (claves `PRIMEKG_NEO4J_*`):

```bash
grafos/primekg_integrado/neo4j/crear_contenedor.sh     # una sola vez
python grafos/primekg_integrado/neo4j/cargar_grafo.py
python grafos/primekg_integrado/neo4j/verificar_carga.py
```

Después alcanza con `docker start neo4j-thesis`. La carga es idempotente.
