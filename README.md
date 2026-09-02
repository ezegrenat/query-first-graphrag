# Selección de subgrafo por criterio topológico para GraphRAG biomédico

Mi tesis de la Licenciatura en Ciencias de Datos (UBA), dirigido por Ariel Chernomoretz.

La propuesta es una variación de GraphRAG que **construye el grafo orientado a cada consulta en lugar de particionar un grafo estático**. El recorte del subgrafo relevante no se hace por similaridad semántica sino con un criterio topológico: se toman algoritmos de detección de módulos de enfermedad tomados de la medicina de redes y se los adapta a un grafo de conocimiento heterogéneo, y recién sobre ese subgrafo se corren la detección de comunidades y los resúmenes.

El grafo de base es [OptimusKG](https://arxiv.org/abs/2604.27269).

## Contenido

- [`bitacora.md`](bitacora.md) — la idea general del trabajo, el algoritmo propuesto, las decisiones tomadas sobre los datos y el estado de la experimentación. Se actualiza a medida que el trabajo avanza.

## Estado

En curso. Actualmente estoy trabajando en calibración de parámetros y la revisión de archivos en los que ya vine trabajando desde hace un mes pero no estaban en este repo. 
