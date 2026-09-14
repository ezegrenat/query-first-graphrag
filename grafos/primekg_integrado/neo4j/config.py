"""Conexion al contenedor neo4j-thesis, el que tiene PrimeKG integrado, y rutas de sus CSV.

Es un contenedor aparte del que tiene OptimusKG porque la edicion community de Neo4j tiene una
sola base por instancia. Puertos distintos para que puedan coexistir, aunque con poca RAM conviene
tener levantado uno solo a la vez.

Las credenciales se leen del entorno, no del codigo, igual que en el loader de OptimusKG: copiar
.env.example a .env en la raiz del repositorio y completarlo. Las claves llevan el prefijo PRIMEKG_
para que los dos grafos puedan convivir en el mismo .env.
"""
import os

CONTENEDOR = "neo4j-thesis"
PUERTO_WEB = 7475
PUERTO_BOLT = 7688


def _cargar_env():
    #cuatro niveles arriba: neo4j/ -> primekg_integrado/ -> grafos/ -> raiz del repositorio.
    #Lo que ya este definido en el entorno gana sobre el archivo
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as archivo:
        for linea in archivo:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env()

NEO4J_URI = os.environ.get("PRIMEKG_NEO4J_URI", f"bolt://localhost:{PUERTO_BOLT}")
NEO4J_USER = os.environ.get("PRIMEKG_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("PRIMEKG_NEO4J_PASSWORD")
if not NEO4J_PASSWORD:
    raise SystemExit("falta PRIMEKG_NEO4J_PASSWORD: copiar .env.example a .env y completarlo, "
                     "o exportar la variable en el entorno")

#los CSV del grafo, en datos/processed/ (no se versionan, ver el README de la carpeta). El loader
#los lee directamente y colapsa las aristas a una por par el mismo, para no depender de ningun
#notebook
_AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA_PROCESADOS = os.path.join(_AQUI, "..", "datos", "processed")
ARCHIVO_NODOS = os.path.join(CARPETA_PROCESADOS, "merged_nodes.csv")
ARCHIVO_ARISTAS = os.path.join(CARPETA_PROCESADOS, "merged_edges.csv")
ARCHIVO_ESTRELLAS = os.path.join(CARPETA_PROCESADOS, "disease_bert_edges.csv")

#de node_type del CSV a label de Neo4j, escrito a mano
LABEL_POR_TIPO = {
    "gene_protein": "Gene",
    "disease": "Disease",
    "pathway": "Pathway",
}

#de edge_type del CSV a tipo de relacion de Neo4j. disease_disease se parte en dos al cargar:
#las aristas padre-hijo de MONDO quedan como DISEASE_DISEASE y las de la estrella de cada grupo
#BERT (las que lista disease_bert_edges.csv) como DISEASE_BERT, para que el experimento pueda
#tomar el plano de enfermedades sin los grupos con un filtro simple
RELACION_POR_TIPO = {
    "ppi": "PPI",
    "gda": "GDA",
    "pathway_protein": "PATHWAY_PROTEIN",
    "form_complex": "FORM_COMPLEX",
    "disease_disease": "DISEASE_DISEASE",
}
RELACION_ESTRELLA = "DISEASE_BERT"

BATCH_SIZE = 5000
MAX_REINTENTOS = 10
