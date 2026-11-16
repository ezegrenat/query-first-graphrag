"""Los textos que PrimeKG trae para los nodos del grafo: la definicion de cada enfermedad y la descripcion de cada
droga. Los genes no tienen texto en PrimeKG y quedan afuera.

Solo entran las definiciones: mondo_definition (y umls_description cuando falta) para enfermedades y description de DrugBank para drogas. 

Esto escribe datos/textos_nodos.parquet con id, label, texto, fuente (mondo_definition, umls_description o
drugbank_description) y mondo_id. Se corre desde cualquier lado con el python del pipeline y no necesita Neo4j.
"""
import os

import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "datos")
ARCHIVO_NODOS_GRAFO = os.path.join(AQUI, "..", "..", "evaluacion", "grafo_entero", "nodos.parquet")
ARCHIVO_NODOS_INTEGRADO = os.path.join(DATOS, "processed", "merged_nodes.csv")
ARCHIVO_PUENTE_CUI = os.path.join(DATOS, "processed", "disease_mappings.csv")
ARCHIVO_NODOS_PRIMEKG = os.path.join(DATOS, "external", "primekg_nodes.csv")
ARCHIVO_FEATURES_ENFERMEDADES = os.path.join(DATOS, "external", "primekg_disease_features.csv")
ARCHIVO_FEATURES_DROGAS = os.path.join(DATOS, "external", "drug_features.csv")
ARCHIVO_DROGAS_DETALLE = os.path.join(AQUI, "grafo_laboratorio", "grafo", "drogas_detalle.csv")
ARCHIVO_SALIDA = os.path.join(DATOS, "textos_nodos.parquet")


def texto_de_fila(fila):
    """(texto, fuente) de una fila de features de enfermedades: la definicion de MONDO y si no la de UMLS."""
    if isinstance(fila["mondo_definition"], str) and fila["mondo_definition"].strip():
        return fila["mondo_definition"].strip(), "mondo_definition"
    if isinstance(fila["umls_description"], str) and fila["umls_description"].strip():
        return fila["umls_description"].strip(), "umls_description"
    return None, None


def filas_de_enfermedades():
    """Las filas de features con texto, una por cada (node_index, mondo_id). El CSV repite el par con la misma definicion o con una vacia, asi que se prefiere la fila que tiene texto."""
    features = pd.read_csv(ARCHIVO_FEATURES_ENFERMEDADES, low_memory=False,
                           usecols=["node_index", "mondo_id", "mondo_name", "mondo_definition", "umls_description"])
    textos = features.apply(texto_de_fila, axis=1, result_type="expand")
    features["texto"], features["fuente"] = textos[0], textos[1]
    features = features.sort_values("texto", na_position="last", kind="stable")
    return features.drop_duplicates(["node_index", "mondo_id"]).reset_index(drop=True)


def textos_de_cuis(nodos_integrado, features):
    """Una fila por CUI del grafo con texto: id, texto, fuente y mondo_id."""
    cuis = nodos_integrado[(nodos_integrado.node_type == "disease") & (nodos_integrado.node_source == "disgenet")]
    puente = pd.read_csv(ARCHIVO_PUENTE_CUI, index_col=0, usecols=["Unnamed: 0", "diseaseId", "mondo_id", "prime_node_index"])
    puente = puente[puente.diseaseId.isin(cuis.node_id)].dropna(subset=["prime_node_index"])
    puente["prime_node_index"] = puente.prime_node_index.astype(int)
    cruce = puente.merge(features, left_on=["prime_node_index", "mondo_id"], right_on=["node_index", "mondo_id"],
                         how="left")
    print(f"enfermedades por CUI: {len(cuis)} en el grafo, {len(puente)} con puente a PrimeKG, "
          f"{cruce.node_index.notna().sum()} con fila exacta (node_index, mondo_id), "
          f"{cruce.texto.notna().sum()} con texto")
    con_texto = cruce.dropna(subset=["texto"])
    return pd.DataFrame({"id": con_texto.diseaseId.values, "texto": con_texto.texto.values,
                         "fuente": con_texto.fuente.values, "mondo_id": con_texto.mondo_id.values})


def textos_de_grupos(nodos_integrado, nodos_primekg, features):
    """Una fila por grupo BERT con texto. La fila de features elegida es la del miembro que se llama como el grupo y,
    si no hay, la del miembro de nombre mas corto con texto."""
    grupos = nodos_integrado[(nodos_integrado.node_type == "disease") & (nodos_integrado.node_source == "primekg")]
    enfermedades_primekg = nodos_primekg[nodos_primekg.node_type == "disease"]
    indice_por_id = pd.Series(enfermedades_primekg.node_index.values, index=enfermedades_primekg.node_id)
    if not grupos.node_id.isin(indice_por_id.index).all():
        raise ValueError("hay grupos BERT sin nodo en PrimeKG")
    miembros = features.dropna(subset=["texto"])
    filas, por_nombre, por_mas_corto = [], 0, 0
    for id_grupo, nombre in zip(grupos.node_id, grupos.node_name):
        candidatos = miembros[miembros.node_index == indice_por_id[id_grupo]]
        if candidatos.empty:
            continue
        iguales = candidatos[candidatos.mondo_name.str.lower() == nombre.lower()]
        if not iguales.empty:
            fila = iguales.iloc[0]
            por_nombre += 1
        else:
            fila = candidatos.loc[candidatos.mondo_name.str.len().idxmin()]
            por_mas_corto += 1
        filas.append({"id": id_grupo, "texto": fila.texto, "fuente": fila.fuente, "mondo_id": fila.mondo_id})
    print(f"grupos BERT: {len(grupos)} en el grafo, {len(filas)} con texto "
          f"({por_nombre} por el miembro que se llama como el grupo, {por_mas_corto} por el miembro de nombre mas corto)")
    return pd.DataFrame(filas)


def textos_de_drogas(nodos_primekg):
    """Una fila por droga del grafo con descripcion de DrugBank. Una droga con varios drugbank_id (sales que
    comparten compuesto) toma la primera que tenga descripcion."""
    detalle = pd.read_csv(ARCHIVO_DROGAS_DETALLE, usecols=["node_id", "drugbank_id"]).dropna(subset=["drugbank_id"])
    drogas_primekg = nodos_primekg[nodos_primekg.node_type == "drug"]
    indice_por_id = pd.Series(drogas_primekg.node_index.values, index=drogas_primekg.node_id)
    descripciones = pd.read_csv(ARCHIVO_FEATURES_DROGAS, usecols=["node_index", "description"])
    descripcion_por_indice = descripciones.dropna(subset=["description"]).set_index("node_index").description
    filas = []
    for id_nodo, ids in zip(detalle.node_id, detalle.drugbank_id):
        for drugbank_id in ids.split("|"):
            indice = indice_por_id.get(drugbank_id)
            if indice is not None and indice in descripcion_por_indice.index:
                filas.append({"id": id_nodo, "texto": descripcion_por_indice[indice].strip(),
                              "fuente": "drugbank_description", "mondo_id": None})
                break
    print(f"drogas: {len(detalle)} con drugbank_id en el grafo, {len(filas)} con descripcion en DrugBank")
    return pd.DataFrame(filas)


def imprimir_cobertura(nodos_grafo, textos):
    """Nodos con texto por label y largo de los textos en palabras."""
    con_texto = nodos_grafo.merge(textos.drop(columns="label"), on="id", how="left")
    print("\ncobertura por tipo de nodo:")
    for label, grupo in con_texto.groupby("label"):
        tiene = grupo.texto.notna()
        print(f"  {label}: {tiene.sum()} de {len(grupo)} con texto ({tiene.mean():.3f})"
              + ("" if not tiene.any() else f", fuentes {grupo.fuente.value_counts().to_dict()}"))
    palabras = textos.texto.str.split().str.len()
    print("\nlargo en palabras:")
    for label, grupo in textos.groupby("label"):
        largo = palabras[grupo.index]
        print(f"  {label}: mediana {largo.median():.0f}, percentil 90 {largo.quantile(0.9):.0f}, maximo {largo.max()}")
    print("\ntres ejemplos por tipo, para revisar el cruce:")
    for label, grupo in con_texto.dropna(subset=["texto"]).groupby("label"):
        for fila in grupo.sample(3, random_state=42).itertuples():
            print(f"  [{label} {fila.id}] {fila.nombre} ({fila.fuente}, mondo_id {fila.mondo_id}): {fila.texto[:200]}")


def main():
    nodos_grafo = pd.read_parquet(ARCHIVO_NODOS_GRAFO)
    nodos_integrado = pd.read_csv(ARCHIVO_NODOS_INTEGRADO, dtype={"node_id": str})
    nodos_primekg = pd.read_csv(ARCHIVO_NODOS_PRIMEKG, dtype={"node_id": str})
    features = filas_de_enfermedades()
    textos = pd.concat([textos_de_cuis(nodos_integrado, features).assign(label="Disease"),
                        textos_de_grupos(nodos_integrado, nodos_primekg, features).assign(label="Disease"),
                        textos_de_drogas(nodos_primekg).assign(label="Drug")], ignore_index=True)
    textos = textos[["id", "label", "texto", "fuente", "mondo_id"]]
    if not textos.id.is_unique:
        raise ValueError("hay un nodo con mas de un texto")
    if not textos.id.isin(nodos_grafo.id).all():
        raise ValueError("hay textos de nodos que no estan en el grafo")
    textos.to_parquet(ARCHIVO_SALIDA, index=False)
    print(f"\n{len(textos)} textos en {ARCHIVO_SALIDA}")
    imprimir_cobertura(nodos_grafo, textos)


if __name__ == "__main__":
    main()
