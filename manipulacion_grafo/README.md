# manipulacion_grafo

Scripts usan la selección y la calibracion para leer el grafo de Neo4j

- `planos_y_pasos.py` define los tres planos (es decir las capas de genes, enfermedades y drogas), los seis pasos entre ellos y las consultas al grafo
- `grafo_heterogeneo.py` junta los tres planos y las relaciones entre tipos en una sola matriz, que es un requerimiento para que "camine" RWR
