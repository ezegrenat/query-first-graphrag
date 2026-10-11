"""Conexion al contenedor neo4j-thesis,que tiene PrimeKG integrado, y rutas de sus CSV. Las credenciales se leen del entorno"""
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

#los CSV del grafo, en datos/processed/ 
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


RELACION_POR_TIPO = {
    "ppi": "PPI",
    "gda": "GDA",
    "pathway_protein": "PATHWAY_PROTEIN",
    "form_complex": "FORM_COMPLEX",
    "disease_disease": "DISEASE_DISEASE",
}
RELACION_ESTRELLA = "DISEASE_BERT"

#el grafo de PrimeKG integrado con los compuestos del laboratorio
CARPETA_GRAFO_LABORATORIO = os.environ.get(
    "PRIMEKG_GRAFO_LABORATORIO", os.path.join(_AQUI, "..", "grafo_laboratorio", "grafo"))
ARCHIVO_LAB_NODOS = os.path.join(CARPETA_GRAFO_LABORATORIO, "nodos.csv")
ARCHIVO_LAB_ARISTAS = os.path.join(CARPETA_GRAFO_LABORATORIO, "aristas.csv")
ARCHIVO_LAB_DETALLE = os.path.join(CARPETA_GRAFO_LABORATORIO, "drogas_detalle.csv")

BATCH_SIZE = 5000
MAX_REINTENTOS = 10
