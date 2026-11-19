# Selección del subgrafo de una query

Dadas las entidades de una consulta como nodos del grafo, arma el subgrafo sobre el que después se corren comunidades y resúmenes. Cada entidad busca sus vecinos de los otros dos tipos (las semillas) y en el plano de cada uno expande con DIAMOnD k iteraciones y después C3. Sobre la unión de todo se corre un RWR, que suma los nodos de mayor puntaje de cada tipo. Devuelve el subgrafo que esos nodos inducen en PrimeKG integrado (`neo4j-thesis`).

El módulo es `subgrafo_query.py` y tiene estas funciones

- `cargar_grafo` abre la conexión y carga los tres planos y el grafo heterogéneo, una sola vez.
- `seleccionar` devuelve los nodos con su procedencia, o sea qué entidad trajo a cada uno, por qué paso y con qué método.
- `filtrar_configuracion` se queda con una de las cuatro configuraciones de la evaluación (semillas, diamond, diamond_c3 y completa). Las cuatro salen de la misma selección.
- `materializar_subgrafo` trae de Neo4j los nodos y las aristas entre ellos.
- `obtener_subgrafo_query` encadena todo.

Los planos y los pasos están en `../manipulacion_grafo/planos_y_pasos.py` y los algoritmos en `../expansion/`. El k de cada paso sale de `../calibracion/`. `cache_planos/` guarda los planos en `.npz`, se genera solo y no se versiona.

Hace falta `neo4j-thesis` levantado. Se corre con `PYTHONHASHSEED=42`, porque los empates de DIAMOnD se resuelven según el orden de los sets de Python.
