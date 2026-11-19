# expansion

Los algoritmos que agrandan un determinado conjunto de nodos de interes. Todos son llamados por `seleccion_subgrafo/subgrafo_query.py`

- `adyacencia.py` arma la red de un plano desde Neo4j,  el grafo que reciben los algoritmos
- `diamond_algoritmo.py` es DIAMOnD, sacado del repositorio de sus autores
- `c3_algoritmo.py` es C3, también tomado de su autor
- `diamond_c3_algoritmo.py` corre DIAMOnD k iteraciones para  después hacer C3
- `rwr.py` es el Random Walk with Restart sobre el grafo heterogéneo
