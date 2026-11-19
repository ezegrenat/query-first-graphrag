# calibracion

El experimento que elige cuántas iteraciones de DIAMOnD (k) se deben usan en cada paso. Funciona con `neo4j-thesis` levantado y se corre con `PYTHONHASHSEED=42`

Son: 

- `sorteo.py` elige los casos del experimento
- `batch.py` corre cada caso con sus dos tipos de controles y su recall
- `graficos_calibracion.py` calcula las curvas medias, el k de cada paso y los dos graficos

Notar que los 3 usan los siguientes scripts: 

- `celdas.py` tiene la carpeta de resultados y el cache de planos
- `corrida.py` es una corrida de DIAMOnD en un plano
- `controles.py` arma las semillas al azar y las apareadas por grado
- `recall.py` esconde parte de las semillas y mide cuantas se recuperan
