# graphrag

El pipeline completo, que va desde la pregunta hasta la respuesta con GraphRAG. En orden: 

- `pipeline.py`. Enlaza las entidades de cada pregunta, luego selecciona el subgrafo relevante para esa pregunta, lo indexa y lo consulta para responder 
- `requirements_graphrag.txt` 

 `entidades/` tiene:

- `linkear_entidades.py` detecta las entidades de la pregunta y las lleva a nodos del grafo
- `prompt_menciones.txt` es el prompt de la detección

`rag/` tiene: 

- `graphrag_msft.py` arma el proyecto de GraphRAG con el subgrafo ya hecho, lo indexa y lo consulta
- `verbalizar.py` pasa cada arista a una oración en inglés
- `consultar.py` hace la consulta por la API y guarda el contexto que recibió el modelo
- `formatos.py` tiene el formato de respuesta de cada tarea
- `llm.py` tiene los modelos y la llamada a Ollama
- `plantilla/` tiene los prompts de GraphRAG que se copian a cada proyecto
