"""Pasa las aristas de un subgrafo a oraciones en ingles, que son las descripciones de las relaciones en GraphRAG.
Al construir el graphRAG via repo de Microsoft se usa la opcion 'bring_your_own_graph'.
Esta opcion requiere que se pase descripciones de los tipos de relaciones, en este script se construyen esas descripciones segun el tipo de arista (gda, associated_with, etc). 
"""


def frase(tipo, nombre_a, label_a, nombre_b, label_b):
    """La oracion de una arista. Para las relaciones entre tipos distintos se ordenan los extremos por label."""
    if tipo == "DRUG_TARGET":
        droga, gen = (nombre_a, nombre_b) if label_a == "Drug" else (nombre_b, nombre_a)
        return f"The drug {droga} targets the protein encoded by {gen}."
    if tipo == "GDA":
        gen, enfermedad = (nombre_a, nombre_b) if label_a == "Gene" else (nombre_b, nombre_a)
        return f"The gene {gen} is associated with {enfermedad}."
    if tipo == "INDICATION":
        droga, enfermedad = (nombre_a, nombre_b) if label_a == "Drug" else (nombre_b, nombre_a)
        return f"The drug {droga} is indicated for {enfermedad}."
    if tipo == "PPI":
        return f"The proteins {nombre_a} and {nombre_b} interact."
    if tipo == "FORM_COMPLEX":
        return f"The proteins {nombre_a} and {nombre_b} form a complex."
    if tipo == "DRUG_DRUG":
        return f"The drugs {nombre_a} and {nombre_b} are chemically similar."
    if tipo == "PATHWAY_PROTEIN":
        gen, pathway = (nombre_a, nombre_b) if label_a == "Gene" else (nombre_b, nombre_a)
        return f"The protein encoded by {gen} participates in the pathway {pathway}."
    if tipo in ("DISEASE_DISEASE", "DISEASE_BERT"):
        return f"The diseases {nombre_a} and {nombre_b} are related."
    return f"{nombre_a} is related to {nombre_b} ({tipo})."
