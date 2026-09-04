# Selección de subgrafo por criterio topológico para GraphRAG biomédico

Mi tesis de la Licenciatura en Ciencias de Datos (UBA), dirigido por Ariel Chernomoretz.

La propuesta es una variación de GraphRAG que **construye el grafo orientado a cada consulta en lugar de particionar un grafo estático**. El recorte del subgrafo relevante no se hace por similaridad semántica sino con un criterio topológico: se toman algoritmos de detección de módulos de enfermedad tomados de la medicina de redes y se los adapta a un grafo de conocimiento heterogéneo, y recién sobre ese subgrafo se corren la detección de comunidades y los resúmenes.

El grafo de base es [OptimusKG](https://arxiv.org/abs/2604.27269).

## Contenido

- [`bitacora.md`](bitacora.md) :  la idea general del trabajo, el algoritmo propuesto, las decisiones tomadas sobre los datos y el estado de la experimentación. Se actualiza a medida que el trabajo avanza.
- `loader/` :  la carga de OptimusKG a Neo4j. Descarga los parquet publicados en Dataverse y los inserta por lotes.
- `preparacion_grafo/` :  separación de las enfermedades reales del resto de la capa `Disease`, que mezcla enfermedades con rasgos y mediciones de estudios de asociación genómica.
- `expansion/` :  las dos piezas sobre las que corre el paso de expansión. `adyacencia.py` extrae de Neo4j la red de un plano y la deja en memoria como matriz dispersa, mientras que el `diamond_algoritmo.py` es DIAMOnD casi tal cual sacado del repositorio de sus autores.

## para reproducirlo

Hace falta Python 3.12 o superior (lo que exige el paquete de OptimusKG) y Docker.

**1. Levantar Neo4j.** con la versión Community alcanza:

```bash
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/una_password neo4j:5-community
```

**2. Instalar las dependencias y configurar las credenciales:**

```bash
pip install -r requirements.txt
cp .env.example .env      # y editarlo con la password del paso anterior
```

El `.env` no se versiona: cada quien usa el suyo. `loader/config.py` lo lee al importarse, así que no hay que exportar nada a mano.

**3. Carga del grafo:**

```bash
python loader/load_neo4j.py
```

Descarga los parquet de OptimusKG desde Dataverse y los inserta. La carga tarda y conviene dejarla corriendo. Es idempotente: usa `MERGE` e itera en lotes de 5.000 filas, de modo que si se corta se puede volver a lanzar sin duplicar nada.

**4. Marcar las enfermedades reales:**

```bash
python preparacion_grafo/marcar_enfermedades_reales.py
```

Escribe la propiedad `is_truly_disease` en los nodos de la capa `Disease` y crea su indice. Acepta `--revertir` para deshacerlo.

El criterio y las mediciones que lo justifican están en `preparacion_grafo/limpieza_capa_disease.ipynb`, que se puede leer sin ejecutar porque conserva las salidas.


## Estado

En curso. Actualmente estoy trabajando en calibración de parámetros y la revisión de archivos en los que ya vine trabajando desde hace un mes pero no estaban en este repo. 
