"""Arma la capa de drogas del laboratorio resuelta a los ids de PrimeKG integrado y la escribe en capa_resuelta/, para que neo4j/cargar_capa_drogas.py la cargue sin cruzar nada.

Uso, desde esta carpeta:
    /home/ezequel/tesis/.venv-optimuskg/bin/python armar_capa_drogas.py


- Nodos droga: las drogas de PrimeKG con alguna indicacion que estan en la red del laboratorio (cruzan por ChEMBL o por CCD de BioLiP contra su tabla de compuestos). 

- Droga a enfermedad: solo la relacion indication de PrimeKG, llevada a los nodos Disease de PrimeKG integrado con la misma regla que uso la tesis de origen para pegar la jerarquia de MONDO: al grupo BERT si el nodo de PrimeKG es un agrupamiento, a los CUIs mapeados si es un MONDO suelto.

- Droga a gen: traducida de UniProt a Entrez por la tabla uniprot_a_geneid.tsv (abajo).

- Droga a droga: la matriz de similaridad Braun-Blanquet restringida a las 859, todos los pares con similaridad 0,6 o mas

La tabla uniprot_a_geneid.tsv: la arma este mismo script a partir del archivo de ID mapping humano de UniProt, HUMAN_9606_idmapping_selected.tab.gz, que se baja a mano una vez del FTP de UniProt (current_release/knowledgebase/idmapping/by_organism/) y se deja en esta carpeta junto con relnotes.txt del mismo release, renombrado HUMAN_9606_idmapping_selected.relnotes.txt. El archivo trae una fila por accession humana (Swiss-Prot y TrEMBL) con su GeneID de NCBI, que es el Entrez con el que PrimeKG integrado identifica a los genes. Se usa solo el archivo humano porque PrimeKG integrado es de genes humanos (ver ../genes_humanos.ipynb): una diana de otra especie no tiene a que pegarse, y una accession que no esta en el archivo queda sin fila. La tabla recortada a las accessions de 04_bioact se reescribe en cada corrida, con su registro de fuente en uniprot_a_geneid.FUENTE.txt (archivo, fecha, release). Para citarla: The UniProt Consortium, "UniProt: the Universal Protein Knowledgebase in 2025", Nucleic Acids Research, 2025, y el release que dice el FUENTE.

Archivos de entrada, en esta carpeta salvo los de PrimeKG integrado y PrimeKG:
    01_drogas_con_chembl_ccd_smiles.csv   las drogas de PrimeKG con indicacion, con ChEMBL y CCD 
    04_drogas_TDR.csv                      los compuestos de la red de drogas: CID, chembl_id, biolip_id
    04_tclus_TDR.csv                       el cluster identitario de cada CID
    04_bioact_TDR.csv                      compuesto a proteina (UniProt), positive o negative, origen
    02_similitud_interna_drogas.csv        matriz 1.523 x 1.523 de similaridad entre drogas
    HUMAN_9606_idmapping_selected.tab.gz   ID mapping humano de UniProt, bajado a mano (ver arriba), con su relnotes.txt al lado
    uniprot_a_geneid.tsv                   accession humana de UniProt a GeneID, la escribe este script a partir del anterior
    ../datos_ingriz/datos_tesis_ingrid/external/primekg_nodes.csv y primekg_edges.csv   PrimeKG nativo
    ../datos_ingriz/datos_tesis_ingrid/processed/merged_nodes.csv                       los nodos de PrimeKG integrado
    ../datos_ingriz/datos_tesis_ingrid/processed/disease_mappings.csv                   CUI a nodo de PrimeKG

Salida, en capa_resuelta/ (una fila por nodo o por arista, ids como texto):
    nodos_drogas.csv   id, name, chembl_id, ccd, cid_labo, cluster_id
    drug_disease.csv   drug_id, disease_id, mondo_node_id     (disease_id es CUI o id de grupo BERT)
    drug_gene.csv      drug_id, gene_id, origen                (gene_id es Entrez)
    drug_drug.csv      drug_a, drug_b, weight                  (drug_a < drug_b)

Una regla que atraviesa todos los cruces: antes de cada merge se descartan las filas con la clave vacia, porque pandas empareja vacio con vacio y eso infla los cruces.
"""
import datetime
import os

import numpy as np
import pandas as pd

_AQUI = os.path.dirname(os.path.abspath(__file__))
_INTEGRADO = os.path.join(_AQUI, "..", "datos_ingriz", "datos_tesis_ingrid")
ARCHIVO_NODOS_INTEGRADO = os.path.join(_INTEGRADO, "processed", "merged_nodes.csv")
ARCHIVO_PUENTE_CUI = os.path.join(_INTEGRADO, "processed", "disease_mappings.csv")
ARCHIVO_NODOS_PRIMEKG = os.path.join(_INTEGRADO, "external", "primekg_nodes.csv")
ARCHIVO_ARISTAS_PRIMEKG = os.path.join(_INTEGRADO, "external", "primekg_edges.csv")

ARCHIVO_DROGAS_01 = os.path.join(_AQUI, "01_drogas_con_chembl_ccd_smiles.csv")
ARCHIVO_COMPUESTOS_LAB = os.path.join(_AQUI, "04_drogas_TDR.csv")
ARCHIVO_CLUSTERS_LAB = os.path.join(_AQUI, "04_tclus_TDR.csv")
ARCHIVO_BIOACTIVIDAD = os.path.join(_AQUI, "04_bioact_TDR.csv")
ARCHIVO_MATRIZ = os.path.join(_AQUI, "02_similitud_interna_drogas.csv")
ARCHIVO_UNIPROT = os.path.join(_AQUI, "uniprot_a_geneid.tsv")
CARPETA_SALIDA = os.path.join(_AQUI, "capa_resuelta")

#el piso de similaridad que se guarda
SIMILARIDAD_MINIMA = 0.6

ARCHIVO_IDMAPPING_HUMANO = os.path.join(_AQUI, "HUMAN_9606_idmapping_selected.tab.gz")
ARCHIVO_RELNOTES_UNIPROT = os.path.join(_AQUI, "HUMAN_9606_idmapping_selected.relnotes.txt")
URL_IDMAPPING_HUMANO = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/HUMAN_9606_idmapping_selected.tab.gz"


#las drogas


def drogas_de_la_capa():
    """Devuelve (nodos, pares). 
    
    nodos: una fila por droga de PrimeKG que esta en la red del laboratorio, con id (DrugBank), name, chembl_id, ccd, cid_labo y cluster_id. 
    
    pares: todos los pares (drugbank_id, CID).  cid_labo es el menor cid."""
    drogas = pd.read_csv(ARCHIVO_DROGAS_01, dtype=str)
    compuestos = pd.read_csv(ARCHIVO_COMPUESTOS_LAB, dtype=str, usecols=["CID", "chembl_id", "biolip_id"])
    clusters = pd.read_csv(ARCHIVO_CLUSTERS_LAB, dtype=str)

	#para las drogas sin chemb_id vacio, se toma cada par (droga, compuesto) que comparte el id de chembl 
    por_chembl = drogas.dropna(subset=["chembl_id"]).merge(
        compuestos.dropna(subset=["chembl_id"]), on="chembl_id")
        #ppara las drogas sin chemb_id vacio, se toma cada par (droga, compuesto), mismo que arriba pero para ccd
    por_ccd = drogas.dropna(subset=["ccd_id_biolip"]).merge(
        compuestos.dropna(subset=["biolip_id"]), left_on="ccd_id_biolip", right_on="biolip_id")
        #se juntan los dos cruces, se eliminan repetidos y se seleccionan solo las columnas que importan 
    pares = pd.concat([por_chembl, por_ccd])[["drugbank_id", "CID"]].drop_duplicates()
	#drogas que aparecen en algun par de pares 
    nodos = drogas[drogas.drugbank_id.isin(pares.drugbank_id)].copy()
    	#se asigna un cid por droga 
    nodos["cid_labo"] = nodos.drugbank_id.map(pares.assign(CID=pares.CID.astype(int)).groupby("drugbank_id").CID.min())
    
    	#se asigna un cluster por droga 
    nodos["cluster_id"] = nodos.cid_labo.map(clusters.set_index(clusters.drug.astype(int)).cluster_id.astype(int))
    if nodos.cluster_id.isna().any():
        raise ValueError("hay drogas cuyo CID no esta en 04_tclus_TDR.csv")
    nodos = nodos.rename(columns={"drugbank_id": "id", "droga": "name", "ccd_id_biolip": "ccd"})
    nodos = nodos[["id", "name", "chembl_id", "ccd", "cid_labo", "cluster_id"]].sort_values("id")
    return nodos.reset_index(drop=True), pares

#droga a enfermedad

def puente_enfermedades(nodos_integrado, nodos_primekg):
    """Tabla prime_index, integrado_id: 
    a que nodos Disease de PrimeKG integrado le pasa sus aristas cada nodo enfermedad de PrimeKG. Cada grupo BERT lleva la identidad del nodo agrupado de PrimeKG con el mismo node_id. Cada CUI apunta por disease_mappings.csv a un prime_node_index, y recibe aristas solo si ese nodo no es un grupo, si lo es la identidad la lleva el grupo nada mas"""
    enfermedades = nodos_integrado[nodos_integrado.node_type == "disease"]
    grupos = enfermedades[enfermedades.node_source == "primekg"]
    cuis = enfermedades[enfermedades.node_source == "disgenet"]
    prime = nodos_primekg[nodos_primekg.node_type == "disease"]
    indice_por_id = pd.Series(prime.node_index.values, index=prime.node_id)

    puente_grupos = pd.DataFrame({"prime_index": grupos.node_id.map(indice_por_id).values,
                                  "integrado_id": grupos.node_id.values})
    if puente_grupos.prime_index.isna().any():
        raise ValueError("hay grupos BERT de PrimeKG integrado sin nodo en PrimeKG")
    puente_grupos["prime_index"] = puente_grupos.prime_index.astype(int)

    mapeos = pd.read_csv(ARCHIVO_PUENTE_CUI, index_col=0).dropna(subset=["prime_node_index"])
    mapeos = mapeos[mapeos.diseaseId.isin(cuis.node_id)]
    mapeos = mapeos[~mapeos.prime_node_index.astype(int).isin(puente_grupos.prime_index)]
    puente_cuis = pd.DataFrame({"prime_index": mapeos.prime_node_index.astype(int).values,
                                "integrado_id": mapeos.diseaseId.values})
    return pd.concat([puente_cuis, puente_grupos], ignore_index=True)


def indicaciones_de_primekg(nodos_primekg):
    """Los pares droga a enfermedad de la relacion indication de PrimeKG: drugbank_id, disease_index, disease_node_id. Se lee por chunks y se conserva la fila con la droga en x."""
    nodos = nodos_primekg.set_index("node_index")
    partes = []
    for chunk in pd.read_csv(ARCHIVO_ARISTAS_PRIMEKG, usecols=["relation", "x_index", "y_index"], chunksize=1_000_000):
        chunk = chunk[chunk.relation == "indication"]
        es_droga_a_enfermedad = (chunk.x_index.map(nodos.node_type) == "drug") & (chunk.y_index.map(nodos.node_type) == "disease")
        partes.append(chunk[es_droga_a_enfermedad])
    pares = pd.concat(partes, ignore_index=True)
    return pd.DataFrame({"drugbank_id": nodos.loc[pares.x_index, "node_id"].values,
                         "disease_index": pares.y_index.values,
                         "disease_node_id": nodos.loc[pares.y_index, "node_id"].values})


def aristas_droga_enfermedad(nodos, puente, indicaciones):
    """drug_id, disease_id, mondo_node_id: las indicaciones de las drogas de la capa llevadas a los nodos Disease de PrimeKG integrado por el puente. mondo_node_id es el nodo de PrimeKG del que vino."""
    cruce = indicaciones[indicaciones.drugbank_id.isin(nodos.id)].merge(puente, left_on="disease_index", right_on="prime_index")
    aristas = pd.DataFrame(
    {
    "drug_id": cruce.drugbank_id.values, 
    "disease_id": cruce.integrado_id.values,                        
    "mondo_node_id": cruce.disease_node_id.astype(str).values
    }
    )
    aristas = aristas.drop_duplicates(subset=["drug_id", "disease_id"]).sort_values(["drug_id", "disease_id"])
    return aristas.reset_index(drop=True)


#droga a gen


def tabla_uniprot_a_geneid():
    """Escribe uniprot_a_geneid.tsv (accession, geneids con |) con las accessions de 04_bioact que estan en el archivo de ID mapping humano de UniProt, y deja el registro de fuente al lado. Las dianas de otras especies y las accessions inactivas no estan en el archivo y quedan sin fila"""
    if not os.path.exists(ARCHIVO_IDMAPPING_HUMANO):
        raise FileNotFoundError(f"falta {ARCHIVO_IDMAPPING_HUMANO}: bajarlo de {URL_IDMAPPING_HUMANO} y dejarlo en esta carpeta")
    #cada target_id se parte por coma porque 36 son dos accessions pegadas (fusiones de cristalografia)
    bioactividad = pd.read_csv(ARCHIVO_BIOACTIVIDAD, dtype=str, usecols=["target_id"])
    accessions = {a for t in bioactividad.target_id.unique() for a in t.split(",")}
    #22 columnas sin cabecera, se usan la primera (UniProtKB-AC) y la tercera (GeneID de NCBI, varios separados por "; ")
    mapeo = pd.read_csv(ARCHIVO_IDMAPPING_HUMANO, sep="\t", header=None, usecols=[0, 2], names=["accession", "geneids"], dtype=str).fillna("")
    tabla = mapeo[mapeo.accession.isin(accessions)].copy()
    #el separador pasa a | para que mapeo_uniprot_a_entrez lo parta igual que antes
    tabla["geneids"] = tabla.geneids.str.replace("; ", "|", regex=False)
    tabla = tabla.sort_values("accession")
    tabla.to_csv(ARCHIVO_UNIPROT, sep="\t", index=False)
    release = open(ARCHIVO_RELNOTES_UNIPROT).readline().strip() if os.path.exists(ARCHIVO_RELNOTES_UNIPROT) else "sin relnotes.txt al lado"
    fecha_archivo = datetime.date.fromtimestamp(os.path.getmtime(ARCHIVO_IDMAPPING_HUMANO)).isoformat()
    with open(os.path.splitext(ARCHIVO_UNIPROT)[0] + ".FUENTE.txt", "w") as archivo:
        archivo.write(f"uniprot_a_geneid.tsv: accessions humanas de UniProt de 04_bioact_TDR.csv con su GeneID de NCBI.\n"
                      f"Escrita el {datetime.date.today().isoformat()} por armar_capa_drogas.py a partir de {os.path.basename(ARCHIVO_IDMAPPING_HUMANO)} "
                      f"(bajado el {fecha_archivo} de {URL_IDMAPPING_HUMANO}), columnas UniProtKB-AC y GeneID (EntrezGene).\n"
                      f"Release de UniProt: {release}.\n"
                      f"Accessions en 04_bioact: {len(accessions)}, humanas en el archivo: {len(tabla)}, con GeneID: {(tabla.geneids != '').sum()}, "
                      f"de otras especies o inactivas (sin fila): {len(accessions) - len(tabla)}.\n")


def mapeo_uniprot_a_entrez(genes_integrado):
    """target_id, gene_id: para cada diana de la bioactividad, los genes de PrimeKG integrado a los que llega. Un target_id con coma (fusiones de cristalografia de BioLiP) se parte y la mitad que no es humana se pierde sola. Una accession con varios GeneID en PrimeKG integrado da varias filas."""
    tabla_uniprot_a_geneid()
    tabla = pd.read_csv(ARCHIVO_UNIPROT, sep="\t", dtype=str).fillna("").drop_duplicates(subset=["accession"])
    geneids = dict(zip(tabla.accession, tabla.geneids))
    dianas = pd.read_csv(ARCHIVO_BIOACTIVIDAD, dtype=str, usecols=["target_id"]).target_id.unique()
    filas = [{"target_id": diana, "gene_id": gen}
             for diana in sorted(dianas)
             for accession in diana.split(",")
             for gen in geneids.get(accession, "").split("|")
             if gen in genes_integrado]
    return pd.DataFrame(filas).drop_duplicates()


def aristas_droga_gen(pares, mapeo):
    """drug_id, gene_id, origen: las actividades positive de las drogas de la capa con la diana traducida a Entrez, una fila por par. origen es chembl, biolip o both (both tambien si el par llego por los dos por separado)."""
    bioactividad = pd.read_csv(ARCHIVO_BIOACTIVIDAD, dtype=str, usecols=["drug_id", "target_id", "activity_tag", "origen"])
    positivas = bioactividad[bioactividad.activity_tag == "positive"].merge(pares, left_on="drug_id", right_on="CID")
    con_gen = positivas.merge(mapeo, on="target_id")
    origen = con_gen.groupby(["drugbank_id", "gene_id"]).origen.agg(
        lambda valores: "both" if len(set(valores)) > 1 or "both" in set(valores) else valores.iloc[0])
    aristas = origen.reset_index().rename(columns={"drugbank_id": "drug_id"})
    return aristas.sort_values(["drug_id", "gene_id"]).reset_index(drop=True)


#---------------------------------------------------------------- droga a droga


def aristas_droga_droga(nodos):
    """drug_a, drug_b, weight: los pares de drogas de la capa con similaridad Braun-Blanquet de SIMILARIDAD_MINIMA o mas. Se toma el triangulo superior de la matriz con los ids ordenados, asi cada par aparece una vez y drug_a < drug_b."""
    matriz = pd.read_csv(ARCHIVO_MATRIZ, index_col=0)
    ids = sorted(nodos.id)
    if set(ids) - set(matriz.index):
        raise ValueError("hay drogas de la capa que no estan en la matriz de similaridad")
    valores = matriz.loc[ids, ids].to_numpy(dtype=np.float32)
    if not np.allclose(valores, valores.T):
        raise ValueError("la matriz no es simetrica")
    filas, columnas = np.triu_indices(len(ids), k=1)
    pesos = valores[filas, columnas]
    pasan = pesos >= SIMILARIDAD_MINIMA
    return pd.DataFrame({"drug_a": np.array(ids)[filas[pasan]], "drug_b": np.array(ids)[columnas[pasan]],
                         "weight": pesos[pasan].round(4)})


#---------------------------------------------------------------- verificaciones y escritura


def verificar_y_escribir(nodos, drug_disease, drug_gene, drug_drug, nodos_integrado, genes_integrado):
    """Comprueba la forma de la capa (no los numeros, que estan en el documento de construccion), escribe los cuatro CSV e imprime un resumen."""
    ids = set(nodos.id)
    enfermedades_integrado = set(nodos_integrado[nodos_integrado.node_type == "disease"].node_id)
    assert nodos.id.is_unique, "id de droga repetido"
    assert drug_disease.drug_id.isin(ids).all() and drug_disease.disease_id.isin(enfermedades_integrado).all(), "INDICATION con extremo fuera del grafo"
    assert drug_gene.drug_id.isin(ids).all() and drug_gene.gene_id.isin(genes_integrado).all(), "DRUG_TARGET con extremo fuera del grafo"
    assert drug_drug.drug_a.isin(ids).all() and drug_drug.drug_b.isin(ids).all(), "DRUG_DRUG con droga fuera de la capa"
    assert not drug_disease.duplicated(subset=["drug_id", "disease_id"]).any(), "INDICATION repetida"
    assert not drug_gene.duplicated(subset=["drug_id", "gene_id"]).any(), "DRUG_TARGET repetida"
    assert (drug_drug.drug_a < drug_drug.drug_b).all() and not drug_drug.duplicated().any(), "DRUG_DRUG repetida o desordenada"
    assert drug_drug.weight.between(SIMILARIDAD_MINIMA, 1.0).all(), "weight fuera de rango"

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    for nombre, tabla in [("nodos_drogas", nodos), ("drug_disease", drug_disease), ("drug_gene", drug_gene), ("drug_drug", drug_drug)]:
        tabla.to_csv(os.path.join(CARPETA_SALIDA, f"{nombre}.csv"), index=False)

    con_enfermedad, con_gen = set(drug_disease.drug_id), set(drug_gene.drug_id)
    con_similar = set(drug_drug.drug_a) | set(drug_drug.drug_b)
    print(f"capa_resuelta/: {len(nodos)} nodos Drug, {len(drug_disease)} INDICATION, {len(drug_gene)} DRUG_TARGET, "
          f"{len(drug_drug)} DRUG_DRUG (similaridad >= {SIMILARIDAD_MINIMA})")
    print(f"drogas con enfermedad {len(con_enfermedad)}, con gen {len(con_gen)}, con droga parecida {len(con_similar)}, "
          f"con las tres {len(con_enfermedad & con_gen & con_similar)}, sin ninguna arista {len(ids - con_enfermedad - con_gen - con_similar)}")


def main():
    nodos, pares = drogas_de_la_capa()
    nodos_integrado = pd.read_csv(ARCHIVO_NODOS_INTEGRADO, dtype={"node_id": str})
    nodos_primekg = pd.read_csv(ARCHIVO_NODOS_PRIMEKG, dtype={"node_id": str})
    genes = nodos_integrado[nodos_integrado.node_type == "gene_protein"].node_id
    genes_integrado = set(genes[~genes.str.startswith("SIGNOR")])  #sin los 421 complejos de SIGNOR

    drug_disease = aristas_droga_enfermedad(nodos, puente_enfermedades(nodos_integrado, nodos_primekg),
                                            indicaciones_de_primekg(nodos_primekg))
    drug_gene = aristas_droga_gen(pares, mapeo_uniprot_a_entrez(genes_integrado))
    drug_drug = aristas_droga_droga(nodos)
    verificar_y_escribir(nodos, drug_disease, drug_gene, drug_drug, nodos_integrado, genes_integrado)


if __name__ == "__main__":
    main()
