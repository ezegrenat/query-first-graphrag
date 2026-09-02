"""Configuracion del loader: credenciales de Neo4j y catalogo de tipos del grafo.

Las credenciales se leen del entorno, no del codigo. La forma mas comoda de fijarlas es copiar
.env.example a .env en la raiz del repositorio y completarlo: este modulo lo lee al importarse, asi
que no hace falta exportar nada a mano ni pasar la contraseña por linea de comandos.

NEO4J_PASSWORD no tiene valor por defecto a proposito. Si falta, el programa corta con un error
claro en vez de intentar conectarse con una contraseña equivocada y fallar mas adelante por una
razon que no se entiende.
"""
import os


def _cargar_env():
    """Vuelca el .env de la raiz del repositorio en os.environ, si existe.

    Se hace a mano en vez de con python-dotenv para no sumar una dependencia por diez lineas. Lo
    que ya este definido en el entorno gana sobre el archivo, que es el orden habitual: permite
    pisar un valor puntual sin editar el .env.
    """
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
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

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
try:
    NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
except KeyError:
    raise SystemExit(
        "falta NEO4J_PASSWORD: copiar .env.example a .env y completarlo, "
        "o exportar la variable en el entorno")

BATCH_SIZE = 5000

NODE_TYPES = [
    "anatomy", "biological_process", "cellular_component", "disease", "drug",
    "exposure", "gene", "molecular_function", "pathway", "phenotype",
]

EDGE_TYPES = [
    "anatomy_anatomy", "anatomy_gene",
    "biological_process_biological_process", "biological_process_gene",
    "cellular_component_cellular_component", "cellular_component_gene",
    "disease_disease", "disease_gene", "disease_phenotype",
    "drug_biological_process", "drug_disease", "drug_drug", "drug_gene", "drug_phenotype",
    "exposure_biological_process", "exposure_cellular_component", "exposure_disease",
    "exposure_exposure", "exposure_gene", "exposure_molecular_function",
    "gene_gene",
    "molecular_function_gene", "molecular_function_molecular_function",
    "pathway_gene", "pathway_pathway",
    "phenotype_gene", "phenotype_phenotype",
]

#cada tipo de relacion conecta un tipo de nodo origen con uno destino. no se puede derivar
#partiendo el nombre del archivo por "_" (varios tipos de nodo ya tienen "_" en su propio
#nombre, ej. "biological_process"), asi que se arma a mano.
EDGE_TYPE_NODE_TYPES = {
    "anatomy_anatomy": ("anatomy", "anatomy"),
    "anatomy_gene": ("anatomy", "gene"),
    "biological_process_biological_process": ("biological_process", "biological_process"),
    "biological_process_gene": ("biological_process", "gene"),
    "cellular_component_cellular_component": ("cellular_component", "cellular_component"),
    "cellular_component_gene": ("cellular_component", "gene"),
    "disease_disease": ("disease", "disease"),
    "disease_gene": ("disease", "gene"),
    "disease_phenotype": ("disease", "phenotype"),
    "drug_biological_process": ("drug", "biological_process"),
    "drug_disease": ("drug", "disease"),
    "drug_drug": ("drug", "drug"),
    "drug_gene": ("drug", "gene"),
    "drug_phenotype": ("drug", "phenotype"),
    "exposure_biological_process": ("exposure", "biological_process"),
    "exposure_cellular_component": ("exposure", "cellular_component"),
    "exposure_disease": ("exposure", "disease"),
    "exposure_exposure": ("exposure", "exposure"),
    "exposure_gene": ("exposure", "gene"),
    "exposure_molecular_function": ("exposure", "molecular_function"),
    "gene_gene": ("gene", "gene"),
    "molecular_function_gene": ("molecular_function", "gene"),
    "molecular_function_molecular_function": ("molecular_function", "molecular_function"),
    "pathway_gene": ("pathway", "gene"),
    "pathway_pathway": ("pathway", "pathway"),
    "phenotype_gene": ("phenotype", "gene"),
    "phenotype_phenotype": ("phenotype", "phenotype"),
}

#campos de `properties` que se descartan por completo al cargar a Neo4j (no aportan para
#busqueda/navegacion y son pesados: por ejemplo los blobs de moleculas en base64 de `drug`).
#`homologues` (genes homologos en otras especies) llega a pesar >350KB por fila en ~25000/61306
#genes (>1GB en total en gene.parquet): al concentrarse varias filas grandes en el mismo batch de
#escritura, el mensaje Bolt se vuelve tan pesado que Neo4j corta la conexion (BrokenPipeError) a
#mitad de carga, sin loggear ningun error de memoria ni de Cypher. confirmado inspeccionando
#gene.parquet directamente: sin este campo, el resto de las propiedades de gene pesan poco.
CAMPOS_EXCLUIR = {"mol_file_base64", "mol_image_base64", "homologues"}

#reintentos ante TransientError (interbloqueos/conflictos de lock en Neo4j), con backoff
#exponencial (2 ** intento segundos entre reintentos).
MAX_REINTENTOS = 10


def label_de(tipo_nodo):
    """Convierte "biological_process" -> "BiologicalProcess" (convención PascalCase de Neo4j)."""
    return "".join(parte.capitalize() for parte in tipo_nodo.split("_"))
