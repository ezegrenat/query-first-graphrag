# Selección de subgrafo por criterio topológico para GraphRAG biomédico

Este repositorio contiene el trabajo de mi tesis de Licenciatura en Ciencias de Datos (UBA), dirigida por Ariel Chernomoretz. El objetivo es responder consultas en lenguaje natural sobre biomedicina combinando un grafo de conocimiento con un modelo de lenguaje y el uso de una variación sobre GraphRAG.

## Motivación y resumen corto del trabajo

Proponer una implementación de GraphRAG que construya su grafo orientado a una query, en lugar de tener un grafo estático que sirva para cualquier query. Concretamente, esto es cambiar el pipeline de la estructura agregando un criterio topológico. Se trabaja sobre un gran grafo de conocimiento de biomedicina.

## El problema

Se utiliza al grafo de conocimiento [OptimusKG](https://arxiv.org/abs/2604.27269), que contiene cientos de miles de nodos relacionados a drogas, fenotipos, genes, enfermedad y más y millones de aristas. El grafo es completamente heterogéneo.  

El pipeline de referencia para esta tarea es *GraphRAG*, esquema de Microsoft descrito en *From Local to Global* (Edge et al., 2025), que consiste en detectar comunidades (entendiendo por comunidad a un conjunto de nodos más densamente conectados entre si que con el resto del grafo) sobre el grafo completo, resumir cada comunidad con un modelo de lenguaje, y responder a partir de esos resúmenes. 

Ese esquema supone que la detección de comunidades y los resúmenes se calculan **una sola vez, sin conocer la consulta**, y se reutilizan después. La objeción práctica es de costo: resumir con un modelo de lenguaje las comunidades de un grafo de 190.531 nodos no es viable en hardware modesto, y el trabajo se hace igual aunque la consulta toque una porción diminuta del grafo.

## La idea de este trabajo

Se invierte el orden. En vez de particionar todo el grafo y filtrar después, **primero se recorta el subgrafo relevante a la consulta y recién sobre ese subgrafo se corre la detección de comunidades**. Lo que se ganaría no es solo costo: las comunidades que salen ya están orientadas a la consulta, en vez de ser una partición genérica del grafo entero.

La selección de este subgrafo relevante a la consulta no utiliza criterios de similaridad semántica, sino topológicos. Se toman algoritmos ya usados en la medicina de redes orientados a detectar módulos de enfermedades y se los adapta al contexto de un grafo altamente heterogéneo como es OptimusKG. 

## El algoritmo

La pieza de base es DIAMOnD (Ghiassian, Menche & Barabási, 2015), un algoritmo que hace crecer un módulo de enfermedad agregando de a un nodo por iteración. Por *módulo* se entiende el conjunto de genes asociados a una enfermedad y sus vecinos más cercanos en la red de interacción entre proteínas. En cada iteración DIAMOnD evalúa todos los nodos vecinos al módulo actual y agrega aquel cuya conectividad resulte más improbable bajo un modelo hipergeométrico. La diferencia con simplemente elegir el nodo con más conexiones al módulo es justamente esa corrección por grado, que evita que el algoritmo se llene de *hubs* sin relación específica con la consulta.
DIAMOnD es un algoritmo muy intuitivo en su diseño y útil, pero está definido para redes homogéneas: supone que todos los nodos son del mismo tipo y todas las aristas significan lo mismo. OptimusKG no cumple ninguna de las dos cosas. Ante esta situación, se propone que **La forma de respetar ese supuesto sin renunciar al grafo heterogéneo es separar el salto entre tipos de la expansión propiamente dicha.**

Llamamos "entidades" a cualquier parte de la consulta a utilizar en la obtención del grafo relevante. Por ejemplo, "¿Qué tienen en común la enfermedad celíaca y el asma?" tendría como entidad a los nodos (en este caso, nodos pertenecientes a la capa Disease) celiaquía y asma. 

Dada una entidad de la consulta, perteneciente a una capa A, se corre, para cada capa B (que incluye a A):

1. **Cosecha**: se traen los vecinos de tipo B que la entidad tiene en el grafo, a través de la relación bipartita que une A con B. Esos vecinos son llamados semillas.
2. **Expansión**: se corre DIAMOnD sobre el plano homogéneo B–B (es decir, la red que forman los nodos de tipo B entre sí), sembrado con esas semillas y con un corte de iteraciones calibrado para ese par en particular.

El salto entre tipos lo hace enteramente la cosecha, y las corridas de DIAMOnD nunca cambian de tipo: entra con nodos de tipo B y sale con nodos de tipo B. Los cuatro pasos parten siempre de la entidad de la consulta, no hay realimentación de un paso a otro. 

Sobre esa unión de expansiones se corre después un *random walk* multicapa para conectar los fragmentos, y recién al final se traen de la base todas las aristas reales entre los nodos seleccionados, con su tipo de relación.

Como la entidad de la consulta puede ser de cualquiera de los cuatro tipos, el espacio total es de 16 pasos posibles (4 tipos de origen × 4 de destino), de los cuales cada consulta usa los 4 que corresponden a su tipo.

## Qué se está midiendo actualmente

Cada paso necesita saber cuántas iteraciones correr antes de frenar (es un parámetro de DIAMOnD), y ese número no puede ser el mismo para todos: las redes involucradas difieren en tamaño y densidad en varios órdenes de magnitud. El experimento en curso caracteriza cada uno de los 16 pasos por separado, midiendo cómo crece el módulo iteración a iteración contra dos modelos nulos: uno que toma las semillas al azar de forma uniforme y otro que propone una comparación más justa haciendo la selección de semillas también tomadas al azar pero "apareadas" por grado con las semillas reales. Este protocolo de recuperación cruzada es tomada del paper que presenta DIAMOnD y en el también se esconde el 30% de las semillas para luego medir cuántas recupera el algoritmo. 


## Decisiones importantes

- **Se trabaja únicamente con las capas Disease, Drug, Phenotype y Gene**, que además de ser las que concentran mayor volumen son las que pueden ser más relevantes para nuestras queries. Más adelante podría considerarse expandir este método hacia las demás capas del grafo.    

- **Para las expansiones de DIAMOnD, nos quedamos con un único tipo de arista intracapa**, de forma en que se conserve el presupuesto de homogeneidad que requiere el algoritmo. Estas son las aristas que son más relevantes dentro de cada una de las capas:
    - **Gene**: `INTERACTS_WITH`, el interactoma, con 322 mil aristas entre 18 mil genes. 
    
    - **Disease**: `PARENT` y **Phenotype**: `PARENT`. En los dos casos es la única relación intracapa disponible.
    - **Drug**: `PARENT`. Es la única capa que ofrecía dos opciones: la alternativa era `SYNERGISTIC_INTERACTION`.

- **Solo se usan las asociaciones de mayor evidencia.** Las aristas `ASSOCIATED_WITH`, que conecta al par `Gene` y `Disease` y al par `Gene` y `Phenotype` son mayoritariamente asociaciones con bajísimo nivel de evidencia. Se establecerá un filtro sobre estas para que el grafo de conocimiento represente relaciones más confiables.

- **La capa de enfermedades está filtrada.** De los más de 36 mil nodos etiquetados como enfermedad en OptimusKG, poco más de 17 mil lo son: el resto son rasgos y mediciones cuantitativas provenientes de estudios de asociación genómica, más algunos fenotipos y procedimientos. La separación usa la jerarquía de la ontología y está documentada en `preparacion_grafo/`.

## Bajo qué criterio se filtra el evidence score
En el paper de OptimusKG se puede leer que el `EVIDENCE_SCORE` está tomado de OpenTargets, y yendo a https://platform-docs.opentargets.org/associations se ve lo siguiente: 

"For all cases, the Platform defines a data source association score by 
calculating a harmonic sum using the full vector of evidence scores adefined for each data source using the following the next steps: The pieces of evidence are sorted in descending order and assigned an incremental value that indicates their position in the sorted list (the top-scoring item has a positional id of 1, the second has a positional id of 2, and so on). The harmonic sum for each data source is then calculated by summing the result of dividing each evidence score by (positional id^2). To ensure the result  is between 0 and 1, the harmonic sum is normalised by dividing the result by the maximum theoretical harmonic sum, which is the one calculated using an infinite vector of ones."

Más adelante: 

"The overall association score aims to summarise all the aggregated evidence for a given target-disease association. The score is derived by calculating the harmonic sum of the association score by data source weighted by the data source weights, regardless of their data type categorisation. The algorithm to compute the scores is the same as the association by data source, resulting in a score between 0 and 1.". Más abajo, se detallan los siguientes weight factors para distintas fuentes de datos: Europe PMC 0,2; Expression Atlas 0,2; IMPC 0,2; OTAR projects 0,5; Cancer Biomarkers 0,5; "others" 1,0. 

Y luego: 

"There are a few important considerations regarding association scores. As described above, association scores are a heuristic based on the availability of data. While scores are useful to rank lists of targets or diseases, they should not be interpreted as a confidence score for the target-disease association. 

For example, **under-studied diseases are unlikely to produce high-scoring targets due to the lack of available evidence. In such diseases, a relatively low-scoring target might still be the top-ranked target and potentially a very interesting lead from a therapeutic standpoint**."

En resumen: se puede afirmar que filtrar un evidence score >= 0.5 esperando que eso sea "hay mas evidencia a favor que en contra" 
sería un error... el evidnece score es una heurística de disponibilidad de datos y no una confianza en la asociación.


## Estado

Actualmente estoy trabajando en la calibración de las iteraciones para cada tipo de capa. 
