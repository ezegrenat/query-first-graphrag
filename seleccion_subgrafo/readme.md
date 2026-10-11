# Selección del subgrafo de una query

Dadas las entidades de una consulta como nodos del grafo, proyecta cada una con DIAMOnD (o, con `metodo`, con C3 o DIAMOnD k + C3) en los planos donde tiene vecinos, une las proyecciones y devuelve el subgrafo que inducen en PrimeKG integrado (neo4j-thesis). Es la etapa de recuperación del pipeline: recibe lo que identifica el entity matching y entrega el subgrafo sobre el que después se corren comunidades y resúmenes. Los planos, los pasos y el algoritmo son los mismos de `../calibracion/`.

El módulo es `subgrafo_query.py`, con `obtener_subgrafo_query` como entrada. Lo que hace cada función, sus parámetros, errores y casos borde están en `especificacion.md`. `cache_planos/` guarda los planos en `.npz`; se genera solo y no se versiona.

## Uso

Hace falta `neo4j-thesis` levantado con la capa de drogas cargada, el entorno de la calibración y `PYTHONHASHSEED=42`, sin el cual los nodos que agrega DIAMOnD cambian de una corrida a otra.

```python
from subgrafo_query import cargar_grafo, obtener_subgrafo_query

G = cargar_grafo()
sub = obtener_subgrafo_query(G, [("Disease", "C0007570"), ("Disease", "C0004096")],
                             {"disease_a_gene": 100, "disease_a_drug": 20})
sub.nodos    #label, id, nombre y por qué entró cada uno
sub.aristas  #las del grafo original entre esos nodos, con tipo y propiedades
```


