"""
Dada una query en lenguaje natural se obtienen los nodos del grafo que representan a sus entidades relevantes. Funciona en 4 pasos:

-1 deteccion: qwen marca las entidades de la pregunta, su tipo (drug, disease o gene) y su nombre en ingles usando el prompt_menciones.txt.

-2 normalizacion: se pasa todo a minusculas, sin puntuaciones y con palabras ordenadas.

-3 buscar coincidencias exactas: utilizando un diccionario, se prueban los nombres de los nodos y despues sus sinonimos en otros vocabularios (Disgenet para enfermedades, hgnc para genes y mesh para drogas y mas enfermedades). Si encuentra match, termina aca. Si la misma forma es de varios nodos gana el que mas filas de nombres o sinonimos respaldan; a igual cantidad, si son dos se devuelven los dos (suelen ser el mismo concepto repartido en dos CUI) y si son mas se queda el de nombre mas corto, que es el termino general.

-4 buscar por segmentos: si una enfermedad sigue sin enlazar a esta altura, se toma el segmento de palabras seguidas mas largo que coincida exacto (por ejemplo, "pediatric glioma" pasa a "glioma").

Si siguio sin haber match entonces la mencion queda como "no enlazada" y se reporta.

"""


import json
import os
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from rag.llm import OLLAMA_GPU, Modelo, generar

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = Modelo("ollama", "qwen2.5:7b", OLLAMA_GPU)
PROMPT = os.path.join(AQUI, "prompt_menciones.txt")
#los nodos del grafo, exportados de neo4j-thesis
NODOS = os.path.join(AQUI, "datos", "nodos.parquet")
DISGENET = os.path.join(AQUI, "datos", "disease_mappings.tsv")
HGNC = os.path.join(AQUI, "datos", "hgnc_complete_set.txt")
MESH = os.path.join(AQUI, "datos", "sinonimos_mesh.parquet")
TIPOS = ("Gene", "Disease", "Drug")

MAXIMO_EMPATADOS = 2 #hasta cuantos nodos empatados en votos se devuelven todos
#palabras que no cuentan como contenido y no son tenidas en cuenta
VACIAS = {"of", "the", "and", "or", "with", "without", "in", "to", "a", "an", "s", "disease", "diseases", "syndrome",
          "disorder", "disorders", "nos", "unspecified", "type"}
GENERICAS = {"gene", "genes", "protein", "proteins", "drug", "drugs", "mutation", "mutations", "inhibitor",
             "inhibitors", "patients", "cancer", "tumor", "molecule", "molecules", "variant", "variants",
             "polymorphism", "polymorphisms", "therapy", "treatment", "receptor", "kinase", "kinases", "enzyme",
             "enzymes", "phenotype", "phenotypes", "genetic", "loci", "locus"} #se podran agregar mas


@dataclass(frozen=True)
class Mencion:
    texto: str
    tipo: str
    nombre_en_ingles: str


def normalizar(texto):
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    solo_letras = re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower())
    return solo_letras.strip()


def forma(texto):
    "La forma con la que se compara un nombre: normalizado y con las palabras ordenadas"
    return " ".join(sorted(normalizar(texto).split()))


def sin_parentesis(texto):
    return re.sub(r"\([^)]*\)", " ", texto)


def menciones_de(respuesta):
    "Las menciones de la respuesta del modelo, que vienen en JSON"
    try:
        menciones_crudas = json.loads(respuesta).get("menciones", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    menciones = []
    for m in menciones_crudas:
        if isinstance(m, dict) and m.get("tipo") in TIPOS and m.get("texto"):
            menciones.append(Mencion(m["texto"], m["tipo"], m.get("nombre_en_ingles") or m["texto"]))
    return menciones


def tablas_de_nombres(ruta_nodos):
    "obtener los nombres de los nodos como (tipo, id, nombre) junto con sus sinonimos (tipo, id, nombre), dejando una fila por cada vocabulario"
    nodos = pd.read_parquet(ruta_nodos)
    nodos["nombre"] = nodos["nombre"].astype(str)
    #se deja afuera los grupos BERT ya que que son las enfermedades con id que no es un CUI, y tambien a los compuestos in nombre, a los que se les deja  su codigo de ChEMBL
    grupo_bert = (nodos["label"] == "Disease") & ~nodos["id"].str.startswith("C")
    codigo_chembl = nodos["nombre"].str.fullmatch(r"CHEMBL\d+")
    nombres = nodos[nodos["label"].isin(TIPOS) & ~grupo_bert & ~codigo_chembl]
    nombres = nombres.rename(columns={"label": "tipo"})[["tipo", "id", "nombre"]]

    #por cada vocabulario y cada enfermedad, los sinonimos para ese cui
    disgenet = pd.read_csv(DISGENET, sep="\t", dtype=str, usecols=["diseaseId", "vocabulary", "vocabularyName"])
    disgenet = disgenet.dropna().drop_duplicates()
    disgenet = pd.DataFrame({"tipo": "Disease", "id": disgenet["diseaseId"], "nombre": disgenet["vocabularyName"]})

    #genes: el nombre aprobado, los alias y los simbolos previos de HGNC dados por el entrez_id. los simbolos de menos de tres letras quedan afuera porque son ambiguos
    #por cada gen, sus entrez_id y su nombre
    hgnc = pd.read_csv(HGNC, sep="\t", dtype=str, usecols=["entrez_id", "name", "alias_symbol", "prev_symbol"])
    hgnc = hgnc.melt(id_vars="entrez_id", value_name="nombre").dropna()
    hgnc["nombre"] = hgnc["nombre"].str.split("|")
    hgnc = hgnc.explode("nombre")
    hgnc = hgnc[(hgnc["variable"] == "name") | (hgnc["nombre"].str.len() >= 3)]
    hgnc = pd.DataFrame({"tipo": "Gene", "id": hgnc["entrez_id"], "nombre": hgnc["nombre"]})

    #para enfermedades y drogas los terminos de entrada de MeSH, ya pasados a ids del grafo
    mesh = pd.read_parquet(MESH).rename(columns={"forma": "nombre"})[["tipo", "id", "nombre"]]

    #hay nodos con parentesis. En esos casos se  guarda lo que esta en el parentesis como un sinonimo
    con_parentesis = nombres[nombres["nombre"].str.contains("(", regex=False)]

    sinonimos = pd.concat([disgenet, hgnc, mesh, con_parentesis])
    #los sinonimos se comparan sin lo que tienen entre parentesis ("Drusen (degenerative)")
    sinonimos["nombre"] = sinonimos["nombre"].map(sin_parentesis)
    #solo los sinonimos de nodos que estan en el grafo
    sinonimos = sinonimos.merge(nombres[["tipo", "id"]], on=["tipo", "id"])
    return nombres, sinonimos


def diccionario(tabla):
    """dict (tipo, forma) -> {id: votos}. Cada fila de la tabla dice que un nodo se puede llamar con ese nombre, y le va sumando un voto a ese nodo en la forma de ese nombre. Por como es la normalizacion, la forma no distingue mayusculas puntuacion ni orden de las palabras, asi que por ejemplo las enfemredades Lung cancer, LUNG CANCER y cancer, Lung votan en la misma clave.
    """
    tabla = tabla.assign(forma=tabla["nombre"].map(forma))
    tabla = tabla[tabla["forma"] != ""]
    votos = tabla.groupby(["tipo", "forma", "id"]).size()
    salida = {}
    for (tipo, forma_, id_nodo), cantidad in votos.items():
        salida.setdefault((tipo, forma_), {})[id_nodo] = cantidad
    return salida


class Linkeador:
    "Los diccionarios de nombres y de sinonimos"

    def __init__(self, ruta_nodos=NODOS):
        nombres, sinonimos = tablas_de_nombres(ruta_nodos)
        self.niveles = [diccionario(nombres), diccionario(sinonimos)]
        #la tabla de nombres de cada tipo y el nombre de cada nodo para el desempate y para mostrar
        self.tablas = {tipo: nombres[nombres["tipo"] == tipo].sort_values("id").reset_index(drop=True)
                       for tipo in TIPOS}
        self.nombre_de = dict(zip(zip(nombres["tipo"], nombres["id"]), nombres["nombre"]))

    def exacto(self, tipo, candidatos):
        """Los ids de los nodos cuya forma coincide exacto con algun candidato. primero se prueba con los nombres de los nodos, despues con los sinonimos. la lista queda vacia si no coincide ninguno"""
        for nivel in self.niveles:  #primero nombres y despues sinonimos
            for candidato in candidatos:
                votos = nivel.get((tipo, forma(candidato)), {}) #se pasa al candidato a su forma y se busca la clave (tipo, forma) en el diccionario de nivel. Si no hay, queda {} y votos no tiene ningun nodo
                if votos:
                    return self.desempatar(tipo, votos)
        return []

    def desempatar(self, tipo, votos):
        """Entre los nodos de una misma forma se queda con los de mas votos. Si empatan hasta MAXIMO_EMPATADOS se devuelven todos,  si empatan mas se queda el de nombre mas corto. A igual largo el id menor, para que el resultado no cambie en distintas corridas"""
        mas_votos = max(votos.values())
        empatados = sorted(i for i in votos if votos[i] == mas_votos)
        if len(empatados) <= MAXIMO_EMPATADOS:
            return empatados
        def largo(id_nodo):
            nombre = self.nombre_de[(tipo, id_nodo)]
            return len(normalizar(nombre).split()), len(nombre), id_nodo
        return [min(empatados, key=largo)]

    def segmentos(self, mencion):
        """Los ids del segmento de palabras seguidas mas largo de una enfermedad que coincide exacto. En igual largo va primero el segmento de mas a la derecha, que suele ser el que es el  nucleo de la frase"""
        palabras = normalizar(sin_parentesis(mencion.nombre_en_ingles)).split()
        for largo in range(len(palabras) - 1, 0, -1):
            for inicio in range(len(palabras) - largo, -1, -1):
                segmento = palabras[inicio:inicio + largo]
                if set(segmento) <= VACIAS | GENERICAS:
                    continue
                ids = self.exacto("Disease", [" ".join(segmento)])
                if ids:
                    return ids
        return []

    def linkear_mencion(self, mencion):
        """(tipo, ids, paso) de los nodos de la mencion: casi siempre un solo id, varios cuando empatan en el diccionario. Queda None si no enlaza nada"""
        tipo = mencion.tipo

        candidatos = [sin_parentesis(mencion.nombre_en_ingles), sin_parentesis(mencion.texto)]
        candidatos += re.findall(r"\(([^)]*)\)", mencion.texto)
        ids = self.exacto(tipo, candidatos)
        if ids:
            return tipo, ids, "diccionario"
        if tipo == "Disease":
            ids = self.segmentos(mencion)
            if ids:
                return tipo, ids, "segmentos"
        return None


def linkear_entidades(pregunta, linkeador):
    "entidades como (tipo, id), enlaces como (mencion, tipo, ids, paso) y respuesta del modelo"
    with open(PROMPT) as archivo:
        prompt = archivo.read().replace("{pregunta}", pregunta)
    respuesta, _ = generar(MODELO, prompt, formato_json=True)
    enlaces = []
    for mencion in menciones_de(respuesta):
        enlace = linkeador.linkear_mencion(mencion)
        if enlace:
            enlaces.append((mencion, *enlace))
    #dos menciones que caen en el mismo nodo cuentan una vez
    entidades = list(dict.fromkeys((tipo, id_nodo) for _, tipo, ids, _ in enlaces for id_nodo in ids))
    return entidades, enlaces, respuesta
