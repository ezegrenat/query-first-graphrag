# Selección del subgrafo de una query

Dadas las entidades de una consulta como nodos del grafo, se proyecta cada una con DIAMOnD (o, con "metodo", sea con C3 o DIAMOnD k + C3) en los planos donde tiene vecinos, une las proyecciones y devuelve el subgrafo que inducen en PrimeKG integrado (neo4j-thesis). Es la etapa de recuperación del pipeline: recibe lo que identifica el entity matching y entrega el subgrafo sobre el que después se corren comunidades y resúmenes. Los planos, los pasos y el algoritmo son los mismos de `../calibracion/`.

El módulo es `subgrafo_query.py`, con `obtener_subgrafo_query` como entrada. Lo que hace cada función, sus parámetros, errores y casos borde están en `especificacion.md`. `cache_planos/` guarda los planos en `.npz`; se genera solo y no se versiona.

Hace falta `neo4j-thesis` levantado 
