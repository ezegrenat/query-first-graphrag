# Evaluación con BioASQ

Compara seis configuraciones sobre preguntas de BioASQ 14b que nombran entidades del grafo: el modelo solo, GraphRAG sobre el grafo entero y las cuatro selecciones de subgrafo (semillas, DIAMOnD, DIAMOnD y C3 y completa). Todas usan el mismo modelo qwen y responden tres veces cada pregunta.

Las preguntas de bioasq se bajan del sitio web de la competencia.


## Qué hace cada archivo

En bioasq/:

- comun.py tiene todas las tareas con sus prompts, las configuraciones y las rutas. 
- prompts/ tiene el prompt del reduce de cada tarea entre las evaluadas. 
- preguntas/armar_conjuntos.ipynb enlaza las menciones de cada pregunta a nodos del grafo y tambien se queda con las que caen enteras adentro. Deja las muestras de factoid, list, yes/no y summary.
- preguntas/armar_conjunto_sin_oro.ipynb y armar_conjunto_list_por_oro.ipynb arman dos muestras más: factoid con la respuesta fuera del grafo y list separada según cuánto de la respuesta tiene nodo.
- seleccionar.py arma el subgrafo de cada conjunto de entidades y su proyecto de GraphRAG. Las preguntas que nombran las mismas entidades comparten subgrafo.
- indexar.py indexa esos proyectos con GraphRAG. Un subgrafo sin aristas no se indexa y esa configuración se abstiene.
- responder.py pide las respuestas de las seis configuraciones. Las que usan grafo hacen búsqueda global en nivel 0 
- medir_summary_ragchecker.py y medir_bertscore.py sacan las medidas de summary que necesitan un modelo. 
- metricas.ipynb calcula las medidas de todas las tareas a partir de las respuestas y las deja en medidas_*.csv.
- capitulo_evaluacion/tablas.ipynb arma las tablas con esos CSV. El bootstrap de los intervalos está en ic.py.

En grafo_entero/, indexar_grafo_entero.py arma el índice de GraphRAG sobre el grafo entero, que es la línea de base. Usa los mismos parámetros que seleccionar.py, copiados porque en la máquina con GPU no está todo el pipeline: si se cambian en uno, hay que cambiarlos en el otro.


## Correr

Las muestras salen de los tres cuadernos de bioasq/preguntas/. Después, el índice del grafo entero se arma una sola vez:

```bash
cd evaluacion/grafo_entero
python indexar_grafo_entero.py exportar               
python indexar_grafo_entero.py proyecto --con-texto
python indexar_grafo_entero.py indexar --con-texto    
```

Por cada tarea (factoid, factoid_sin_oro, list, list_por_oro, yesno y summary):

```bash
cd evaluacion/bioasq
PYTHONHASHSEED=42 python seleccionar.py --tarea factoid    # con neo4j-thesis levantado
python indexar.py --tarea factoid                          # en la GPU
python responder.py --tarea factoid --rep 1                # en la GPU, y lo mismo con --rep 2 y --rep 3
```

