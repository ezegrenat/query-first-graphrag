# Selección de subgrafo por criterio topológico para GraphRAG biomédico

Este repositorio contiene el trabajo de mi tesis de Licenciatura en Ciencias de Datos (UBA). El objetivo es responder consultas en lenguaje natural sobre biomedicina combinando un grafo de conocimiento con un modelo de lenguaje y el uso de una variación sobre GraphRAG.

## Motivación y resumen del trabajo

Proponer una implementación de GraphRAG que construya su grafo orientado a una query, en lugar de tener un grafo estático que sirva para cualquier query. Concretamente, esto es cambiar el pipeline de la estructura agregando un criterio topológico. Se trabaja sobre un gran grafo de conocimiento de biomedicina.

## El problema

Se utiliza un grafo de conocimiento que contiene relaciones entre drogas, genes y enfermedades. Este grafo es completamente heterogéneo. 
Se consideró usar [OptimusKG](https://arxiv.org/abs/2604.27269), pero como su capa de drogas estaba muy disconexa se pasó a utilizar una versión enriquecida de PrimeKG. 

El pipeline de referencia para esta tarea es *GraphRAG*, esquema de Microsoft descrito en *From Local to Global* (Edge et al., 2025), que consiste en detectar comunidades (entendiendo por comunidad a un conjunto de nodos más densamente conectados entre si que con el resto del grafo) sobre el grafo completo, resumir cada comunidad con un modelo de lenguaje, y responder a partir de esos resúmenes. 

Ese esquema supone que la detección de comunidades y los resúmenes se calculan **una sola vez, sin conocer la consulta**, y se reutilizan después.

## La idea de este trabajo

Se invierte el orden. En vez de particionar todo el grafo y filtrar después, **primero se recorta el subgrafo relevante a la consulta y recién sobre ese subgrafo se corre la detección de comunidades**. Lo que se ganaría es que las comunidades que salen ya están orientadas a la consulta, en vez de ser una partición genérica del grafo entero.

La selección de este subgrafo relevante a la consulta no utiliza criterios de similaridad semántica, sino topológicos. Se toma un algoritmo ya usado en la medicina de redes homogéneas orientado a detectar módulos de enfermedades y se lo adapta al contexto de un grafo de conocimiento altamente heterogéneo. 


## Construcción del 'PrimeKG enriquecido'

Se tomó una versión enriquecida de PrimeKG creado en [repo_ingrid] y se añadió una capa de drogas [descripción del grafo resultante y el cruce con la capa de drogas] 


## El algoritmo

La pieza de base es DIAMOnD (Ghiassian, Menche & Barabási, 2015), un algoritmo que hace crecer un módulo de enfermedad agregando de a un nodo por iteración. Por *módulo* se entiende el conjunto de genes asociados a una enfermedad y sus vecinos más cercanos en la red de interacción entre proteínas. En cada iteración DIAMOnD evalúa todos los nodos vecinos al módulo actual y agrega aquel cuya conectividad resulte más improbable bajo un modelo hipergeométrico. La diferencia con simplemente elegir el nodo con más conexiones al módulo es justamente esa corrección por grado, que evita que el algoritmo se llene de *hubs* sin relación específica con la consulta.
DIAMOnD es un algoritmo muy intuitivo en su diseño y útil, pero está definido para redes homogéneas: supone que todos los nodos son del mismo tipo y todas las aristas significan lo mismo. Un grafo de conocimiento biomédico no cumple ninguna de las dos cosas. Ante esta situación, se propone que **La forma de respetar ese supuesto sin renunciar al grafo heterogéneo es separar el salto entre tipos de la expansión propiamente dicha.**

Llamamos "entidades" a cualquier parte de la consulta a utilizar en la obtención del grafo relevante. Por ejemplo, "¿Qué tienen en común la enfermedad celíaca y el asma?" tendría como entidad a los nodos (en este caso, nodos pertenecientes a la capa Disease) celiaquía y asma. 

Dada una entidad de la consulta, perteneciente a una capa A, se corre, para cada capa B (que incluye a A):

1. **Cosecha**: se traen los vecinos de tipo B que la entidad tiene en el grafo, a través de la relación bipartita que une A con B. Esos vecinos son llamados semillas.
2. **Expansión**: se corre DIAMOnD sobre el plano homogéneo B–B (es decir, la red que forman los nodos de tipo B entre sí), sembrado con esas semillas y con un corte de iteraciones calibrado para ese par en particular.

El salto entre tipos lo hace enteramente la cosecha, y las corridas de DIAMOnD nunca cambian de tipo: entra con nodos de tipo B y sale con nodos de tipo B. Los cuatro pasos parten siempre de la entidad de la consulta, no hay realimentación de un paso a otro. 

Sobre esa unión de expansiones se corre después un *random walk* multicapa para conectar los fragmentos, y recién al final se traen de la base todas las aristas reales entre los nodos seleccionados, con su tipo de relación.

## Qué se está midiendo actualmente


Se descartó trabajar con OptimusKG. Respecto a la versión enriquecida de PrimeKG se está haciendo una calibración del número de iteración a utilizar en DIAMOnD. 
Cada paso necesita saber cuántas iteraciones correr antes de frenar (es un parámetro de DIAMOnD), y ese número no puede ser el mismo para todos: las redes involucradas difieren en tamaño y densidad en varios órdenes de magnitud. El experimento en curso caracteriza cada uno de los 16 pasos por separado, midiendo cómo crece el módulo iteración a iteración contra dos modelos nulos: uno que toma las semillas al azar de forma uniforme y otro que propone una comparación más justa haciendo la selección de semillas también tomadas al azar pero "apareadas" por grado con las semillas reales. Este protocolo de recuperación cruzada es tomada del paper que presenta DIAMOnD y en el también se esconde el 30% de las semillas para luego medir cuántas recupera el algoritmo. 


## Decisiones importantes

- **Se trabaja únicamente con las capas Disease, Drug y Gene**, que además de ser las que concentran mayor volumen son las que pueden ser más relevantes para nuestras queries. Más adelante podría considerarse expandir este método hacia las demás capas del grafo.    

- **Para las expansiones de DIAMOnD, nos quedamos con un único tipo de arista intracapa**, de forma en que se conserve el presupuesto de homogeneidad que requiere el algoritmo. Estas son las aristas que son más relevantes dentro de cada una de las capas:
    - **Gene**: `PPI`, el interactoma de HIPPIE (interacciones con confianza mayor a 0,73) más SIGNOR. Los complejos proteicos (`FORM_COMPLEX`) quedan fuera del plano para conservar una sola relación.
    - **Disease**: `DISEASE_DISEASE`, la jerarquía padre-hijo de MONDO. Es la única relación intracapa disponible.
    - **Drug**: la similaridad química entre drogas, con el umbral todavía por definir. En OptimusKG la única opción con sentido era `PARENT`, y ese plano resultó demasiado disconexo para trabajar.



## Estado

La calibración de las iteraciones ya está hecha para las dos celdas entre genes y enfermedades sobre el grafo nuevo (ver `calibracion/`). Actualmente estoy trabajando en la capa de drogas: añadir drogas tales que se puedan incorporar bien al PrimeKG enriquecido.
