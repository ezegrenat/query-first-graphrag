# Sistemas de uso y recupero de información almacenados en grafos de conocimiento biomédico para grandes modelos de lenguaje

Los grandes modelos de lenguaje (LLM) se volvieron una forma habitual de buscar y resumir información, pero responden con lo que aprendieron durante el entrenamiento. Cuando les falta un dato tienden a producir de todos modos una respuesta plausible pero incorrecta. La generación aumentada por recuperación (RAG) busca reducir ese problema recuperando fragmentos de texto relevantes y dándoselos al modelo como contexto. GraphRAG organiza además la información en un grafo de entidades y relaciones, lo divide en comunidades y escribe un resumen de cada una para usarlo como contexto.

En el área biomédica existen grafos de conocimiento curados que integran bases de datos de genes, enfermedades y drogas, como PrimeKG. Algunas de sus relaciones forman las redes que estudia la teoría de redes: el interactoma, las asociaciones entre genes y enfermedades y las redes entre drogas y blancos.

En este trabajo se propone un sistema de GraphRAG en el que el grafo que le da contexto al LLM es un subgrafo inducido por la pregunta en lugar del grafo completo. Para eso se construyó el PrimeKG-enriquecido, que une una versión de PrimeKG-curado con la red de compuestos de TDR Targets. Sobre él se armó un sistema que reconoce las entidades que nombra la pregunta, las enlaza a nodos del grafo, luego selecciona un subgrafo a su alrededor con criterios de teoría de redes (semillas, DIAMOnD, C3 y un Random Walk with Restart) y finalmente corre GraphRAG sobre ese subgrafo creado a medida de la pregunta.

Las respuestas se evaluaron con preguntas de BioASQ contra el modelo solo y contra GraphRAG sobre el grafo entero. La selección se asocia con una mejor respuesta cuando trae la respuesta correcta al subgrafo y con una peor cuando no la trae. En tokens, semillas y DIAMOnD gastan menos que el grafo entero sin contar el índice del grafo entero.

Tesis de Licenciatura en Ciencia de Datos, Facultad de Ciencias Exactas y Naturales, Universidad de Buenos Aires, 2026.

![](docs/img/subgrafo_de_una_pregunta.png)

Organización del proyecto
------------

    ├── LICENSE
    ├── README.md
    ├── requirements.txt               <- Entorno de los análisis, la calibración y las tablas
    ├── .env.example                   <- Variables de entorno: Neo4j y el ejecutable de GraphRAG
    │
    ├── grafos/primekg_integrado       <- Construcción del grafo 
    │   ├── grafo_laboratorio          <- Unión de PrimeKG-curado con la red de compuestos de TDR Targets
    │   ├── neo4j                      <- Contenedor de Neo4j y carga del grafo
    │   └── textos_nodos.py            <- Textos de los nodos (definiciones de enfermedades, descripciones de drogas)
    │
    ├── graphrag                       <- De la pregunta a la respuesta (capítulo 4 de la tesis)
    │   ├── pipeline.py                <- El pipeline completo para una pregunta
    │   ├── entidades                  <- Detección de menciones, enlace a nodos y sinónimos de MeSH
    │   └── rag                        <- GraphRAG sobre un subgrafo: verbalización de aristas, índice y consulta
    │       └── plantilla              <- Los prompts de GraphRAG
    │
    ├── seleccion_subgrafo             <- Selección del subgrafo de una pregunta
    ├── expansion                      <- DIAMOnD, C3 y RWR
    ├── manipulacion_grafo             <- Planos homogéneos, pasos y grafo heterogéneo donde camina el RWR
    │
    ├── calibracion                    <- Calibración del k de DIAMOnD en cada paso 
    │   ├── sorteo.py, batch.py        <- El sorteo de los casos y el batch
    │   └── graficos_calibracion.py    <- Las curvas medias y el k de cada paso
    │
    ├── evaluacion                     <- Evaluación con BioASQ 
    │   ├── bioasq
    │   │   ├── preguntas              <- todas las preguntas, menciones y medida del enlace
    │   │   ├── seleccionar.py, indexar.py, responder.py   <- Subgrafos, índices y respuestas de cada configuración
    │   │   ├── metricas.ipynb         
    │   │   ├── medir_summary_ragchecker.py, medir_bertscore.py   <- Medidas de las preguntas summary
    │   │   └── capitulo_evaluacion    <- insumo de tablas de la tesis 
    │   └── grafo_entero               <- Índice de GraphRAG sobre el grafo entero 
    │
    ├── analisis_datos                 <- Tablas descriptivas del grafo y del índice (presentes en los capítulos 3 y 4)
    │
    └── docs
        ├── DATOS.md                   <- Qué datos hay, de dónde salen y dónde se publican
        ├── TRAZABILIDAD.md            <- Qué script da cada tabla y figura de la tesis
        └── subgrafo_de_una_pregunta.ipynb   <- La figura de este README

Los datos no están en el repositorio. El grafo y los resultados de la calibración y de la evaluación deben pedirse al laboratorio.


------------

Este repositorio usa:

- La implementación de DIAMOnD de sus autores (https://github.com/dinaghiassian/DIAMOnD).
- La implementación de C3 de sus autores (https://github.com/wangbingbo2019/C3).
- Los prompts de Microsoft GraphRAG 3.2.0 (https://github.com/microsoft/graphrag).
- El grafo parte del PrimeKG-curado construido en un trabajo anterior del laboratorio hecho por Ingrid Heuer (https://github.com/ingridheuer/gcnn_gdas)
- red de compuestos de TDR Targets v7, presentado en XXXVI Reunión Anual de la Sociedad Argentina de Parasitología.
