from c3_algoritmo import C3, UMBRAL_P
from diamond_algoritmo import DIAMOnD


def DIAMOnD_C3(G_original, seed_genes, k, umbral_p=UMBRAL_P):
    """Corre DIAMOnD k iteraciones y despues C3 desde las semillas mas los agregados de DIAMOnD.

    Devuelve (agregados, n_de_diamond, pasos, motivo_corte):
    - agregados: [(nodo, k, kb, p), ...] en orden, primero los de DIAMOnD y despues los de C3, el mismo contrato que DIAMOnD y C3.
    - n_de_diamond: cuantos de los agregados son de DIAMOnD, que puede ser menos que k si la red se agota antes.
    - pasos y motivo_corte: los de C3, sin cambios.
    """
    seed_genes = set(seed_genes)
    de_diamond = DIAMOnD(G_original, seed_genes, k) if k > 0 else []
    nodos_diamond = {nodo for nodo, *_ in de_diamond}
    de_c3, pasos, motivo_corte = C3(G_original, seed_genes | nodos_diamond, umbral_p)
    return de_diamond + de_c3, len(de_diamond), pasos, motivo_corte
