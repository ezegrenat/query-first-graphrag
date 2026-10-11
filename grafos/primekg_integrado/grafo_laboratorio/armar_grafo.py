"""Arma el grafo de PrimeKG integrado mas la red de compuestos del laboratorio (datos/out_b/) y lo escribe en grafo/. Es el mismo cruce que la seccion 2 (El cruce) de unir_drogas_laboratorio.ipynb, sin el analisis.

Sea D* el grafo resultante de PrimeKG integrado junto con las drogas que tienen indicaciones a enfermedades de el y/o targeteadas a genes de el,

- Nodos droga: uno por compuesto de D*. Entra un compuesto de la red del laboratorio si es una droga de PrimeKG con alguna indicacion (cruza por ChEMBL o por CCD de BioLiP contra su tabla de compuestos) o si tiene bioactividad positiva hacia algun gen del grafo. El cluster identitario queda como propiedad del nodo.

- Droga a enfermedad: solo la relacion indication de PrimeKG

- Droga a gen: las actividades positivas, mapeando de UniProt a Entrez con el archivo de ID mapping humano de UniProt. EL campo origen dice si el par vino de ChEMBL, de BioLiP o de los dos.

- Droga a droga: las aristas del laboratorio entre clusters (similaridad Braunblanquet de 0,81 o mas alta), pasadas a todos los pares de compuestos de D* de los dos clusters.

El archivo de ID mapping humano de UniProt es HUMAN_9606_idmapping_selected.tab.gz

Archivos de entrada:
    datos/01_drogas_con_chembl_ccd_smiles.csv       el listado de las drogas de PrimeKG con indicacion, con ChEMBL y CCD
    datos/out_b/04b_drogas_TDR.csv                  los compuestos de la red: CID, chembl_id, biolip_id  y molweight
    datos/out_b/04b_tclus_TDR.csv                   el cluster identitario de cada CID
    datos/out_b/04b_edges_fp_TDR.csv                similaridad entre clusters, de 0,81 a 0,99
    datos/out_b/04b_bioact_TDR.csv                  compuesto a proteina (UniProt) positive o negative
    datos/HUMAN_9606_idmapping_selected.tab.gz      ID mapping humano de UniProt
    ../datos/external/primekg_nodes.csv y primekg_edges.csv    PrimeKG nativo
    ../datos/processed/merged_nodes.csv, merged_edges.csv y disease_mappings.csv    PrimeKG integrado

Salida, en grafo:
    nodos.csv            
    aristas.csv          
    drogas_detalle.csv  
"""
import os

import numpy as np
import pandas as pd

_AQUI = os.path.dirname(os.path.abspath(__file__))
_CAPA = os.path.join(_AQUI, "datos")
_ENTREGA = os.path.join(_CAPA, "out_b")
_INTEGRADO = os.path.join(_AQUI, "..", "datos")
ARCHIVO_NODOS_INTEGRADO = os.path.join(_INTEGRADO, "processed", "merged_nodes.csv")
ARCHIVO_ARISTAS_INTEGRADO = os.path.join(_INTEGRADO, "processed", "merged_edges.csv")
ARCHIVO_PUENTE_CUI = os.path.join(_INTEGRADO, "processed", "disease_mappings.csv")
ARCHIVO_NODOS_PRIMEKG = os.path.join(_INTEGRADO, "external", "primekg_nodes.csv")
ARCHIVO_ARISTAS_PRIMEKG = os.path.join(_INTEGRADO, "external", "primekg_edges.csv")

ARCHIVO_DROGAS_01 = os.path.join(_CAPA, "01_drogas_con_chembl_ccd_smiles.csv")
ARCHIVO_COMPUESTOS_LAB = os.path.join(_ENTREGA, "04b_drogas_TDR.csv")
ARCHIVO_CLUSTERS_LAB = os.path.join(_ENTREGA, "04b_tclus_TDR.csv")
ARCHIVO_SIMILARIDAD_LAB = os.path.join(_ENTREGA, "04b_edges_fp_TDR.csv")
ARCHIVO_BIOACTIVIDAD = os.path.join(_ENTREGA, "04b_bioact_TDR.csv")
ARCHIVO_IDMAPPING_HUMANO = os.path.join(_CAPA, "HUMAN_9606_idmapping_selected.tab.gz")
CARPETA_SALIDA = os.path.join(_AQUI, "grafo")

COLUMNAS_ARISTA = ["x_index", "y_index", "x_id", "y_id", "x_type", "y_type", "edge_type", "edge_source"]


#el grafo integrado


def grafo_integrado():
    """Devuelve (nodos, aristas, genes) de PrimeKG integrado"""
    nodos = pd.read_csv(ARCHIVO_NODOS_INTEGRADO)
    nodos["node_id"] = nodos.node_id.astype(str)
    filas = pd.read_csv(ARCHIVO_ARISTAS_INTEGRADO)
    filas["x_id"] = filas.x_id.astype(str)
    filas["y_id"] = filas.y_id.astype(str)
    #el CSV guarda cada arista dos veces (una en cada sentido) . si alguna fila no tuviera su inversa, quedarse con x menor que y perderia esa arista sin avisar
    pares = set(zip(filas.x_index, filas.y_index))
    if not all((b, a) in pares for a, b in pares):
        raise ValueError("hay filas de merged_edges.csv sin su inversa")

    if (filas.x_index == filas.y_index).any():
        raise ValueError("merged_edges.csv tiene autobucles")
    aristas = filas[filas.x_index < filas.y_index][COLUMNAS_ARISTA].reset_index(drop=True)
    nodos = nodos[["node_index", "node_id", "node_name", "node_type", "node_source"]]
    genes = nodos[nodos.node_type == "gene_protein"].node_id
    return nodos, aristas, set(genes[~genes.str.startswith("SIGNOR")])


#tratamiendo de las drogas


def drogas_de_la_capa():
    """Devuelve los pares cada droga de PrimeKG con indicacion y cada compuesto de la red del laboratorio con el que comparte el id de ChEMBL o el codigo CCD."""
    drogas = pd.read_csv(ARCHIVO_DROGAS_01, dtype=str)
    compuestos = pd.read_csv(ARCHIVO_COMPUESTOS_LAB, dtype=str, usecols=["CID", "chembl_id", "biolip_id"])

    #para las drogas sin chemb_id vacio, se toma cada par (droga, compuesto) que comparte el id de chembl 
    por_chembl = drogas.dropna(subset=["chembl_id"]).merge(
        compuestos.dropna(subset=["chembl_id"]), on="chembl_id")
    #ppara las drogas sin chemb_id vacio, se toma cada par (droga, compuesto), mismo que arriba pero para ccd
    por_ccd = drogas.dropna(subset=["ccd_id_biolip"]).merge(
        compuestos.dropna(subset=["biolip_id"]), left_on="ccd_id_biolip", right_on="biolip_id")
        
    #se juntan los dos cruces, se eliminan repetidos y se seleccionan solo las columnas que importan 
    pares = pd.concat([por_chembl, por_ccd])[["drugbank_id", "CID"]].drop_duplicates()
    return pares.reset_index(drop=True)


#droga a enfermedad

def puente_enfermedades(nodos_integrado, nodos_primekg):
    """a que nodos Disease de PrimeKG integrado le pasa sus aristas cada nodo enfermedad de PrimeKG. 
    
    Cada grupo BERT lleva la identidad del nodo agrupado de PrimeKG con el mismo node_id. 
    Cada CUI apunta por disease_mappings.csv a un prime_node_index y recibe aristas solo si ese nodo no es un grupo... si lo es la identidad la lleva el grupo nada mas"""
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
    """Los pares droga a enfermedad de la arista indication de PrimeKG"""
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
    """drug_id, disease_id, mondo_node_id: las indicaciones de las drogas de la capa llevadas a los nodos Disease de PrimeKG integrado por el puente. mondo_node_id es el nodo de PrimeKG del que vino"""
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


#drogas a gen


def pares_compuesto_gen(genes):
    """pares CID, gene_id, origen"""
    mapeo = pd.read_csv(ARCHIVO_IDMAPPING_HUMANO, sep="\t", header=None, usecols=[0, 2], names=["accession", "geneids"], dtype=str)
    accession_gen = mapeo.assign(gene_id=mapeo.geneids.str.split("; ")).explode("gene_id").dropna()[["accession", "gene_id"]]

    bioactividad = pd.read_csv(ARCHIVO_BIOACTIVIDAD, dtype=str, usecols=["drug_id", "target_id", "activity_tag", "origen"])
    positivas = bioactividad[bioactividad.activity_tag == "positive"]

    #se parten las fusiones de BioLiop para mapear a cada una por su cuenta
    positivas = positivas.assign(accession=positivas.target_id.str.split(",")).explode("accession")
    # notar que el merge anterior deja afuera las accessions que no estan en el archivo humano
    pares = positivas.merge(accession_gen, on="accession").rename(columns={"drug_id": "CID"})
    pares = pares[pares.gene_id.isin(genes)]

    #un par puede llegar por varias filas. si esas filas traen origenes distintos, o alguna ya dice both, el par es both
    origen = pares.groupby(["CID", "gene_id"]).origen.agg(
        lambda valores: "both" if len(set(valores)) > 1 or "both" in set(valores) else valores.iloc[0])
    return origen.reset_index()


#los nodos nuevos


def nodos_de_d_estrella(pares_droga, pares_gen, primer_indice):
    """Una fila por compuesto de D*, siempre indexada por CID: node_index, node_id, node_name, drugbank_id, chembl_id, ccd, cluster_id y molweight. Entra cualquier compuesto que sea droga del listado o que tenga alguna arista a gen del grafo """
    compuestos = pd.read_csv(ARCHIVO_COMPUESTOS_LAB, dtype=str)
    clusters = pd.read_csv(ARCHIVO_CLUSTERS_LAB, dtype=str)
    drogas = pd.read_csv(ARCHIVO_DROGAS_01, dtype=str, usecols=["drugbank_id", "droga"])

    #el CID se ordena como numero para que los node_index nuevos sigan el orden del laboratorio
    d_estrella = sorted(set(pares_droga.CID) | set(pares_gen.CID), key=int)


    primera_fila = compuestos.drop_duplicates("CID").set_index("CID").loc[d_estrella]
    #de ChEMBL y CCD se guardan todos los ids distintos del compuesto, unidos con |
    chembl_por_cid = (compuestos.dropna(subset=["chembl_id"]).drop_duplicates(["CID", "chembl_id"])
                      .sort_values("chembl_id").groupby("CID").chembl_id.agg("|".join))
    ccd_por_cid = (compuestos.dropna(subset=["biolip_id"]).drop_duplicates(["CID", "biolip_id"])
                   .sort_values("biolip_id").groupby("CID").biolip_id.agg("|".join))
    #las drogas del listado de cada compuesto, con los DrugBank y los nombres unidos. casi siempre es una sola,
    #las excepciones son las sales de citrato y de lactato, que comparten compuesto
    compuesto_con_droga = pares_droga.merge(drogas, on="drugbank_id").sort_values("drugbank_id")
    drogas_del_compuesto = compuesto_con_droga.groupby("CID").agg(drugbank_id=("drugbank_id", "|".join), nombre=("droga", " | ".join))
    return pd.DataFrame({
        "node_index": range(primer_indice, primer_indice + len(d_estrella)),
        "node_id": "CID_" + primera_fila.index,
        #el nombre de la droga si es del listado, si no el primer ChEMBL, y si no tiene ninguno el id del laboratorio
        "node_name": drogas_del_compuesto.nombre.reindex(d_estrella).fillna(primera_fila.chembl_id).fillna(primera_fila.compound_id),
        "drugbank_id": drogas_del_compuesto.drugbank_id.reindex(d_estrella),
        "chembl_id": chembl_por_cid.reindex(d_estrella),
        "ccd": ccd_por_cid.reindex(d_estrella),
        #los compuestos que no estan en 04b_tclus quedan sin cluster
        "cluster_id": clusters.set_index("drug").cluster_id.reindex(d_estrella),
        "molweight": primera_fila.molweight,
    }, index=d_estrella)


#droga a droga


def aristas_droga_droga(nodos_droga):
    """todos los pares CID_a, CID_b, peso  con el peso redondeado a 4 decimales."""
    similaridad = pd.read_csv(ARCHIVO_SIMILARIDAD_LAB, dtype={"clusID1": str, "clusID2": str})
    #cada compuesto con su cluster. los que no tienen cluster no pueden recibir aristas quimicas
    miembros = nodos_droga[["cluster_id"]].rename_axis("CID").reset_index().dropna()
    #se descartan las aristas de un cluster onsigo mismo. el primer merge trae los compuestos del primer cluster y el segundo los del otro, por lo que cada arista se repite para todos los pares. si un cluster no tiene compuestos en D*, el merge no encuentra pareja y la arista se cae
    entre_clusters = similaridad[similaridad.clusID1 != similaridad.clusID2]
    aristas = (entre_clusters
               .merge(miembros.rename(columns={"CID": "CID_a"}), left_on="clusID1", right_on="cluster_id")
               .merge(miembros.rename(columns={"CID": "CID_b"}), left_on="clusID2", right_on="cluster_id"))

    miembros_por_cluster = miembros.cluster_id.value_counts()
    #chequeo de que ningun par se pierde (debería haber tantos pares como el producto de los tamaños de sus dos clusters) 
    esperadas = (entre_clusters.clusID1.map(miembros_por_cluster) * entre_clusters.clusID2.map(miembros_por_cluster)).sum()
    assert len(aristas) == esperadas, "faltan pares al replicar"
    #e redondean a 4 decimales
    return pd.DataFrame({"CID_a": aristas.CID_a, "CID_b": aristas.CID_b, "weight": aristas.weight.round(4)})


#el grafo con los compuestos


def unir_al_grafo_integrado(nodos_integrado, aristas_integrado, nodos_droga, droga_enfermedad, pares_gen, droga_droga):
    """Devuelve (nodos, aristas, aristas_nuevas) con las columnas de PrimeKG integrado"""
    nodos_nuevos = nodos_droga[["node_index", "node_id", "node_name"]].assign(node_type="drug", node_source="laboratorio")
    nodos = pd.concat([nodos_integrado, nodos_nuevos], ignore_index=True)
    indice_por_node_id = nodos_integrado.set_index("node_id").node_index

    #los tres tipos de arista con la misma forma. weight queda vacio salvo en droga a droga, origen salvo en droga a gen
    aristas_drug_disease = pd.DataFrame({
        "x_index": droga_enfermedad.CID.map(nodos_droga.node_index),
        "y_index": droga_enfermedad.disease_id.map(indice_por_node_id),
        "edge_type": "drug_disease",
        "edge_source": "primekg",
    })
    aristas_drug_gene = pd.DataFrame({
        "x_index": pares_gen.CID.map(nodos_droga.node_index),
        "y_index": pares_gen.gene_id.map(indice_por_node_id),
        "edge_type": "drug_gene",
        "edge_source": "laboratorio",
        "origen": pares_gen.origen,
    })
    aristas_drug_drug = pd.DataFrame({
        "x_index": droga_droga.CID_a.map(nodos_droga.node_index),
        "y_index": droga_droga.CID_b.map(nodos_droga.node_index),
        "edge_type": "drug_drug",
        "edge_source": "laboratorio",
        "weight": droga_droga.weight,
    })
    aristas_nuevas = pd.concat([aristas_drug_disease, aristas_drug_gene, aristas_drug_drug], ignore_index=True)

    #los ids y los tipos de los dos extremos, a partir del node_index
    por_indice = nodos.set_index("node_index")
    aristas_nuevas["x_id"] = aristas_nuevas.x_index.map(por_indice.node_id)
    aristas_nuevas["y_id"] = aristas_nuevas.y_index.map(por_indice.node_id)
    aristas_nuevas["x_type"] = aristas_nuevas.x_index.map(por_indice.node_type)
    aristas_nuevas["y_type"] = aristas_nuevas.y_index.map(por_indice.node_type)
    aristas_nuevas = aristas_nuevas[COLUMNAS_ARISTA + ["weight", "origen"]]
    aristas = pd.concat([aristas_integrado, aristas_nuevas], ignore_index=True)
    return nodos, aristas, aristas_nuevas


#verificaciones y escritura


def verificar_y_escribir(nodos, aristas, aristas_nuevas, nodos_droga, droga_enfermedad):
    """un monton de chequeos de la forma del grafo y luego un resumen"""
    assert nodos.node_index.is_unique and nodos.node_id.is_unique, "node_index o node_id repetido"
    assert aristas.x_index.isin(nodos.node_index).all() and aristas.y_index.isin(nodos.node_index).all(), "arista con extremo inexistente"
    assert aristas_nuevas[COLUMNAS_ARISTA].notna().all().all(), "arista nueva con algun campo vacio"
    assert (aristas.x_index != aristas.y_index).all(), "autobucle"
    #se ordena cada par para que (a, b) y (b, a) cuenten como la misma arista
    assert not pd.DataFrame(np.sort(aristas[["x_index", "y_index"]].values, axis=1)).duplicated().any(), "arista repetida"
    tipo_de_y = {"drug_disease": "disease", "drug_gene": "gene_protein", "drug_drug": "drug"}
    assert (aristas_nuevas.x_type == "drug").all(), "arista nueva sin droga en x"
    assert (aristas_nuevas.y_type == aristas_nuevas.edge_type.map(tipo_de_y)).all(), "arista nueva con el tipo equivocado en y"
    droga_a_droga = aristas_nuevas[aristas_nuevas.edge_type == "drug_drug"]
    cluster_por_node_id = nodos_droga.set_index("node_id").cluster_id
    assert (droga_a_droga.x_id.map(cluster_por_node_id) != droga_a_droga.y_id.map(cluster_por_node_id)).all(), "arista dentro de un cluster"
    assert droga_a_droga.weight.between(0.81, 0.99).all(), "weight fuera de rango"
    assert aristas_nuevas[aristas_nuevas.edge_type == "drug_gene"].origen.isin(["chembl", "biolip", "both"]).all(), "origen desconocido"

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    nodos.to_csv(os.path.join(CARPETA_SALIDA, "nodos.csv"), index=False)
    aristas.to_csv(os.path.join(CARPETA_SALIDA, "aristas.csv"), index=False)
    detalle = nodos_droga.assign(tiene_indicacion=nodos_droga.index.isin(droga_enfermedad.CID))
    detalle[["node_id", "drugbank_id", "chembl_id", "ccd", "cluster_id", "molweight", "tiene_indicacion"]].to_csv(
        os.path.join(CARPETA_SALIDA, "drogas_detalle.csv"), index=False)

    print(f"grafo/: {len(nodos)} nodos ({len(nodos_droga)} compuestos nuevos) y {len(aristas)} aristas")
    print("aristas nuevas:", aristas_nuevas.edge_type.value_counts().to_dict())
    print("origen de droga a gen:", aristas_nuevas.origen.value_counts().to_dict())


def main():
    nodos_integrado, aristas_integrado, genes = grafo_integrado()
    pares_droga = drogas_de_la_capa()
    pares_gen = pares_compuesto_gen(genes)
    nodos_droga = nodos_de_d_estrella(pares_droga, pares_gen, nodos_integrado.node_index.max() + 1)


    nodos_primekg = pd.read_csv(ARCHIVO_NODOS_PRIMEKG, dtype={"node_id": str})
    drogas_con_formato_de_la_capa = pd.DataFrame({"id": pares_droga.drugbank_id.unique()})
    drugbank_enfermedad = aristas_droga_enfermedad(drogas_con_formato_de_la_capa,
                                                   puente_enfermedades(nodos_integrado, nodos_primekg),
                                                   indicaciones_de_primekg(nodos_primekg))
    droga_enfermedad = drugbank_enfermedad.merge(pares_droga, left_on="drug_id", right_on="drugbank_id")[["CID", "disease_id"]].drop_duplicates()

    droga_droga = aristas_droga_droga(nodos_droga)
    nodos, aristas, aristas_nuevas = unir_al_grafo_integrado(nodos_integrado, aristas_integrado, nodos_droga, droga_enfermedad, pares_gen, droga_droga)
    verificar_y_escribir(nodos, aristas, aristas_nuevas, nodos_droga, droga_enfermedad)


if __name__ == "__main__":
    main()
