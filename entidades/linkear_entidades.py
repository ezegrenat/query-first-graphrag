"""
Dada una query en lenguaje natural obtener los nodos del grafo que representan a sus entidades relevantes. Funciona en 5 partes: 

1. deteccion: qwen marca las entidades de la pregunta, su tipo (drug, disease o gene) y su nombre en ingles usando el prompt_menciones.txt. 

2. normalizacion: se pasa todo a minusculas, sin puntuaciones y con palabras ordenadas. 

3. buscar coincidencias exactas: utilizando un diccionario, se prueban los nombres de los nodos y despues sus sinonimos en otros vocabularios (Disgenet para enfermedades, hgnc para genes y mesh para drogas y mas enfermedades. Si encuentra match, termina aca. 

4. buscar coincidencias en trigramas: si en el paso anterior sigue sin haber coincidencia entonces se busca el nombre mas parecido por tf.id de trigramas. Si encuentra match, termina aca. 

5. buscar por tramos: si un nodo sigue sin enlazar a esta altura, se toma el tramo de palabras seguidas mas largo que coincida exacto (por ejemplo, "pediatric glioma" pasa a "glioma") 

Si en el paso anterior siguió sin haber match entonces la entidad queda como "no enlazada" y es reportada. 
 
"""


import json
import os
import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from rag.llm import PANDORA, Modelo, generar

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = Modelo("ollama", "qwen2.5:7b", PANDORA)
PROMPT = os.path.join(AQUI, "prompt_menciones.txt")
#los nodos del grafo, exportados de neo4j-thesis
NODOS = os.path.join(AQUI, "datos", "nodos.parquet")
DISGENET = os.path.join(AQUI, "datos", "disease_mappings.tsv")
HGNC = os.path.join(AQUI, "datos", "hgnc_complete_set.txt")
MESH = os.path.join(AQUI, "datos", "sinonimos_mesh.parquet")
TIPOS = ("Gene", "Disease", "Drug")
UMBRAL_TRIGRAMAS = 0.7
#palabras que no cuentan como contenido y no son tenidas en cuenta 
VACIAS = {"of", "the", "and", "or", "with", "without", "in", "to", "a", "an", "s", "disease", "diseases", "syndrome",
          "disorder", "disorders", "nos", "unspecified", "type"}
GENERICAS = {"gene", "genes", "protein", "proteins", "drug", "drugs", "mutation", "mutations", "inhibitor",
             "inhibitors", "patients", "cancer", "tumor", "molecule", "molecules", "variant", "variants",
             "polymorphism", "polymorphisms", "therapy", "treatment", "receptor", "kinase", "kinases", "enzyme",
             "enzymes", "phenotype", "phenotypes", "genetic", "loci", "locus"}


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
    """La forma con la que se compara un nombre: normalizado y con las palabras ordenadas."""
    return " ".join(sorted(normalizar(texto).split()))


def sin_parentesis(texto):
    return re.sub(r"\([^)]*\)", " ", texto)


def menciones_de(respuesta):
    """Las menciones de la respuesta del modelo, que vienen en JSON"""
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
    """obtener los nombres de los nodos como (tipo, id, nombre) junto con sus sinonimos (tipo, id, nombre), dejando una fila por cada vocabulario"""
    nodos = pd.read_parquet(ruta_nodos)
    nodos["nombre"] = nodos["nombre"].astype(str)
    #afuera los grupos BERT ya que que son las enfermedades cuyo id no es un CUI, y tambien a los compuestos in nombre, a los que se les deja  su codigo de ChEMBL
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

    #enfermedades y drogas: los terminos de entrada de MeSH, ya pasados a ids del grafo
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
    """Los diccionarios de nombres y de sinonimos y el TF-IDF de trigramas de cada tipo, armados una vez"""

    def __init__(self, ruta_nodos=NODOS):
        """por cada tipo (drug, gene y disease) guarda un vectorizador propio entrenado solo con los nombres de los nodos de ese tipo"""
        nombres, sinonimos = tablas_de_nombres(ruta_nodos)
        self.niveles = [diccionario(nombres), diccionario(sinonimos)]
        self.tablas, self.vectorizadores, self.matrices = {}, {}, {}
        for tipo in TIPOS:
            tabla = nombres[nombres["tipo"] == tipo].sort_values("id").reset_index(drop=True)
            vectorizador = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3)) #se vectoriza por caracteres (no por palabras) y de a 3 letras 
            self.matrices[tipo] = vectorizador.fit_transform(tabla["nombre"])
            self.vectorizadores[tipo] = vectorizador
            self.tablas[tipo] = tabla

    def similitudes(self, tipo, texto):
        """La similitud coseno de los trigramas de texto con el nombre de cada nodo del tipo"""
        consulta = self.vectorizadores[tipo].transform([texto])
        return (self.matrices[tipo] @ consulta.T).toarray().ravel()

    def exacto(self, tipo, candidatos, mencion):
        """primero se fija si hay match exacto con el nombre, luego con el sinonimo y sino queda None"""
        for nivel in self.niveles:  #primero nombres y despues sinonimos
            for candidato in candidatos:  
                votos = nivel.get((tipo, forma(candidato)), {}) #se pasa al candidato a su forma y se busca la clave (tipo, forma) en el diccionario de nivel. Si no hay, queda {} y votos no tiene ningun nodo 
                if len(votos) == 1: 
                    return next(iter(votos)) #votos es {id: cantidad}. iter recorre las claves y next toma la primera (que es la unica) 
                if len(votos) > 1:
                    #desempate. Se toma la de mas votos y a igual cantidad  votos el nombre mas parecido a la mencion dados por los trigramas 
                    similitud = dict(zip(self.tablas[tipo]["id"], self.similitudes(tipo, mencion.nombre_en_ingles)))
                    #se los retorna en orden para que el resultado no pueda cambiar entre corridas 	
                    return sorted(votos, key=lambda i: (-votos[i], -similitud[i], i))[0]
        return None

    def trigramas(self, tipo, mencion):
        """El id del nodo con nombre mas parecido, siempre que llegue al umbral y no diga nada mas que la mencion. En caso contrario queda None."""
        similitud = self.similitudes(tipo, mencion.nombre_en_ingles)
        mejor = int(np.argmax(similitud))
        if similitud[mejor] < UMBRAL_TRIGRAMAS:
            return None
        #las palabras se comparan por sus cinco primeras letras (o la plaabra entera si no llega a 5). Es un intento de que palabras largas sean tomadas igual en singular o plural. 5 es un valor arbitrario, pero se considero que valores mas cortos empezarian a coincidir palabras muy distintas (que ya significan cosas distintas)  que comparten el mismo comienzo en caracteres 
        palabras_mencion = {p[:5] for p in normalizar(mencion.nombre_en_ingles + " " + mencion.texto).split()}
        palabras_nodo = {p[:5] for p in normalizar(self.tablas[tipo]["nombre"][mejor]).split() if p not in VACIAS}
        if palabras_nodo - palabras_mencion:
            return None
        return self.tablas[tipo]["id"][mejor]

    def tramo(self, mencion):
        """El id del tramo de palabras seguidas mas largo de una enfermedad que coincide exacto. A iguallargo va primero el tramo de mas a la derecha que suele ser nucleo de la frase (pediatric glucoma, lung cancer, etc)"""
        palabras = normalizar(sin_parentesis(mencion.nombre_en_ingles)).split()
        for largo in range(len(palabras) - 1, 0, -1):
            for inicio in range(len(palabras) - largo, -1, -1):
                tramo = palabras[inicio:inicio + largo]
                if set(tramo) <= VACIAS | GENERICAS:
                    continue
                id_nodo = self.exacto("Disease", [" ".join(tramo)], mencion)
                if id_nodo:
                    return id_nodo
        return None

    def linkear_mencion(self, mencion):
        """(tipo, id, paso) del nodo de la mencion. Queda None si no enlaza nada"""
        tipo = mencion.tipo

        candidatos = [sin_parentesis(mencion.nombre_en_ingles), sin_parentesis(mencion.texto)]
        candidatos += re.findall(r"\(([^)]*)\)", mencion.texto)
        id_nodo = self.exacto(tipo, candidatos, mencion)
        if id_nodo:
            return tipo, id_nodo, "diccionario"
        id_nodo = self.trigramas(tipo, mencion)
        if id_nodo:
            return tipo, id_nodo, "trigramas"
        if tipo == "Disease":
            id_nodo = self.tramo(mencion)
            if id_nodo:
                return tipo, id_nodo, "tramo"
        return None


def linkear_entidades(pregunta, linkeador):
    """(entidades como (tipo, id), enlaces con la mencion y el paso que la enlazo, respuesta del modelo)."""
    with open(PROMPT) as archivo:
        prompt = archivo.read().replace("{pregunta}", pregunta)
    respuesta, _ = generar(MODELO, prompt, formato_json=True)
    enlaces = []
    for mencion in menciones_de(respuesta):
        enlace = linkeador.linkear_mencion(mencion)
        if enlace:
            enlaces.append((mencion, *enlace))
    #dos menciones que caen en el mismo nodo cuentan una vez
    entidades = list(dict.fromkeys((tipo, id_nodo) for _, tipo, id_nodo, _ in enlaces))
    return entidades, enlaces, respuesta
