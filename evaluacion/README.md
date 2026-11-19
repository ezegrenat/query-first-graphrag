# Evaluación con BioASQ

Compara seis configuraciones sobre preguntas de BioASQ 14b que nombran entidades del grafo: el modelo solo, GraphRAG sobre el grafo entero y las cuatro selecciones de subgrafo (semillas, DIAMOnD, DIAMOnD y C3 y completa). Todas usan el mismo modelo (qwen3 de 30B) y responden tres veces cada pregunta.

Las preguntas de BioASQ se bajan del sitio de la competencia, con registro, y van en `evaluacion/preguntas/BioASQ-training14b/training14b.json`.


## Qué hace cada archivo

En bioasq/:

- comun.py tiene todas las tareas con sus prompts, las configuraciones y las rutas.
- prompts/ tiene el prompt del reduce de cada tarea entre las evaluadas.
- preguntas/extraer_menciones.py le pide al modelo las menciones de cada pregunta y las deja en extracciones.jsonl.
- preguntas/armar_conjuntos.ipynb enlaza las menciones de cada pregunta a nodos del grafo y también se queda con las que caen enteras adentro. Deja las muestras de factoid, list, yes/no y summary.
- preguntas/armar_conjunto_sin_oro.ipynb y armar_conjunto_list_por_oro.ipynb arman dos muestras más: factoid con la respuesta fuera del grafo y list separada según cuánto de la respuesta tiene nodo.
- preguntas/medir_enlace.py mide cuánto tarda la detección y el enlace en las preguntas de una muestra.
- seleccionar.py arma el subgrafo de cada conjunto de entidades y su proyecto de GraphRAG. Las preguntas que nombran las mismas entidades comparten subgrafo.
- indexar.py indexa esos proyectos con GraphRAG. Un subgrafo sin aristas no se indexa y esa configuración se abstiene. Antes se puede correr reusar_indices.py, que le copia a un subgrafo el índice de otro idéntico de otra tarea.
- responder.py pide las respuestas de las seis configuraciones. Las que usan grafo hacen búsqueda global en nivel 0.
- medir_summary_ragchecker.py y medir_bertscore.py sacan las medidas de summary que necesitan un modelo. Cada uno tiene su entorno (requirements_ragchecker.txt y requirements_bertscore.txt).
- metricas.ipynb calcula las medidas de todas las tareas a partir de las respuestas y las deja en medidas_*.csv.
- capitulo_evaluacion/tablas.ipynb arma las tablas con esos CSV. El bootstrap de los intervalos está en ic.py.
- quitar_texto_bioasq.py copia los resultados sin el texto de BioASQ, para poder compartirlos, y completar_con_bioasq.py lo repone.

En grafo_entero/, indexar_grafo_entero.py arma el índice de GraphRAG sobre el grafo entero, que es la línea de base. Usa los mismos parámetros que seleccionar.py, copiados porque en la máquina con GPU no está todo el pipeline: si se cambian en uno, hay que cambiarlos en el otro.


## Correr

Hace falta `neo4j-thesis` levantado para exportar el grafo y para seleccionar, y una GPU con Ollama para todo lo que llama al modelo (ver `graphrag/rag/llm.py`).

Primero el grafo entero. `exportar` va antes que las muestras, porque `armar_conjuntos.ipynb` lee las aristas que deja. El índice se arma una sola vez:

```bash
cd evaluacion/grafo_entero
python indexar_grafo_entero.py exportar                # con neo4j-thesis levantado
cp nodos.parquet ../../graphrag/entidades/datos/       # el enlace lee los nodos de ahí
python indexar_grafo_entero.py proyecto --con-texto
python indexar_grafo_entero.py indexar --con-texto     # en la GPU, se puede cortar y volver a lanzar
```

Después se extraen las menciones de las preguntas

```bash
cd evaluacion/bioasq/preguntas
python extraer_menciones.py                            # en la GPU
```

y los tres cuadernos, con `armar_conjuntos.ipynb` primero. Con las muestras armadas, `python medir_enlace.py --tarea factoid` (y lo mismo con list, yesno y summary) mide el gasto de la detección.

Por cada tarea (factoid, factoid_sin_oro, list, list_por_oro, yesno y summary):

```bash
cd evaluacion/bioasq
PYTHONHASHSEED=42 python seleccionar.py --tarea factoid    # con neo4j-thesis levantado
python reusar_indices.py --tarea factoid                   # opcional
python indexar.py --tarea factoid                          # en la GPU
python responder.py --tarea factoid --rep 1                # en la GPU, y lo mismo con --rep 2 y --rep 3
```

`PYTHONHASHSEED=42` hace falta porque los empates de DIAMOnD se resuelven según el orden de los sets de Python.

Para summary se corren además las dos medidas, cada una en su entorno

```bash
python medir_summary_ragchecker.py                     # en la GPU
python medir_bertscore.py                              # en la GPU
```

Al final se corre `metricas.ipynb` y después `capitulo_evaluacion/tablas.ipynb`, los dos de arriba abajo.

Con los resultados que da el laboratorio no hace falta nada de lo anterior, alcanza con reponer el texto de BioASQ (`python completar_con_bioasq.py`) y correr `tablas.ipynb`.
