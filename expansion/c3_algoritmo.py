"""algoritmo C3 (connect separate connected components) tomado del repositorio original de los autores: https://github.com/wangbingbo2019/C3 

- El grafo llega ya construido (RedCompacta o algo con nodes, neighbors, degree y number_of_nodes)
 -  Cada nodo del cluster tiene indexada su componente, asi que contar las que toca un candidato cuesta O(grado). El resultado es el mismo.
 -  Donde el original se cae (ningun nodo o ninguna arista con p < 0.05), aca se pasa a aristas o se corta
 - Devuelve los agregados en orden y la LCC la calcula quien lo llama.
"""
from collections import deque

#las funciones del hipergeometrico de C3 son las mismas de DIAMOnD
from diamond_algoritmo import _DictLiviano, compute_all_gamma_ln, pvalue

UMBRAL_P = 0.05


def componentes_del_cluster(neighbors, cluster_nodes):
    """dado un indice nodo retorna componente del subgrafo inducido por el cluster y su cantidad de componentes."""
    componente = {}
    n = 0
    for inicio in cluster_nodes:
        if inicio in componente:
            continue
        componente[inicio] = n
        cola = deque([inicio])
        while cola:
            nodo = cola.popleft()
            for vecino in neighbors[nodo]:
                if vecino in cluster_nodes and vecino not in componente:
                    componente[vecino] = n
                    cola.append(vecino)
        n += 1
    return componente, n


def _links_y_componentes(nodo, neighbors, cluster_nodes, componente):
    ks = 0
    tocadas = set()
    for vecino in neighbors[nodo]:
        if vecino in cluster_nodes:
            ks += 1
            tocadas.add(componente[vecino])
    return ks, tocadas


def reduce_not_in_cluster_nodes(componente, all_degrees, neighbors, cluster_nodes, not_in_cluster):
    """Igual que en el original: de cada kb el nodo de menor k y de cada k el de mayor kb"""
    reduced_not_in_cluster = {}
    kb2k = {}
    for node in not_in_cluster:
        kd = all_degrees[node]
        ks, tocadas = _links_y_componentes(node, neighbors, cluster_nodes, componente)
        kb = len(tocadas)
        k = kd - ks + kb
        kb2k.setdefault(kb, {})[k] = node
    k2kb = {}
    for kb, k2node in kb2k.items():
        min_k = min(k2node.keys())
        node = k2node[min_k]
        k2kb.setdefault(min_k, {})[kb] = node
    for k, kb2node in k2kb.items():
        max_kb = max(kb2node.keys())
        node = kb2node[max_kb]
        reduced_not_in_cluster[node] = (max_kb, k)
    return reduced_not_in_cluster


def aristas_candidatas(neighbors, cluster_nodes, not_in_cluster):
    """Las aristas (vecino del cluster, nodo fuera del cluster)"""
    adyacencia = {}
    for node in not_in_cluster:
        for neighbor in neighbors[node]:
            if neighbor not in cluster_nodes:
                adyacencia.setdefault(node, {})[neighbor] = None
                adyacencia.setdefault(neighbor, {})[node] = None
    vistos = set()
    for node, vecinos in adyacencia.items():
        for neighbor in vecinos:
            if neighbor not in vistos:
                yield node, neighbor
        vistos.add(node)


def reduce_not_in_cluster_edges(componente, all_degrees, neighbors, cluster_nodes, not_in_cluster):
    """Lo mismo para aristas: el k suma los grados de los dos extremos menos la arista misma"""
    reduced_not_in_cluster = {}
    kb2k = {}
    for edge in aristas_candidatas(neighbors, cluster_nodes, not_in_cluster):
        kd = all_degrees[edge[0]] + all_degrees[edge[1]] - 2
        ks1, tocadas1 = _links_y_componentes(edge[0], neighbors, cluster_nodes, componente)
        ks2, tocadas2 = _links_y_componentes(edge[1], neighbors, cluster_nodes, componente)
        kb = len(tocadas1 | tocadas2)
        k = kd - ks1 - ks2 + kb
        kb2k.setdefault(kb, {})[k] = edge
    k2kb = {}
    for kb, k2edge in kb2k.items():
        min_k = min(k2edge.keys())
        edge = k2edge[min_k]
        k2kb.setdefault(min_k, {})[kb] = edge
    for k, kb2edge in k2kb.items():
        max_kb = max(kb2edge.keys())
        edge = kb2edge[max_kb]
        reduced_not_in_cluster[edge] = (max_kb, k)
    return reduced_not_in_cluster


def _mejor(reducidos, N, s0, n, gamma_ln, all_p):
    """(candidato, kb, k, p) de p minimo, o None si no hay candidatos."""
    pmin = 10
    mejor = None
    for candidato, (kb, k) in reducidos.items():
        try:
            p = all_p[(k, kb, n)]
        except KeyError:
            p = pvalue(kb, k, N - s0 + n, n, gamma_ln)
            all_p[(k, kb, n)] = p
        if p < pmin:
            pmin = p
            mejor = (candidato, kb, k, p)
    return mejor


def _descripcion(mejor, reduce):
    """Lo que se guarda del mejor candidato rechazado en el corte."""
    if mejor is None:
        return None
    candidato, kb, k, p = mejor
    return {"candidato": candidato, "kb": kb, "k": k, "p": float(p), "reduce": reduce}


def c3_iteration(G, S, umbral_p=UMBRAL_P):
    """El loop del original. Devuelve (agregados, pasos, motivo_corte)"""
    N = G.number_of_nodes()
    neighbors = _DictLiviano(lambda nodo: set(G.neighbors(nodo)))
    all_degrees = _DictLiviano(G.degree)
    gamma_ln = compute_all_gamma_ln(N + 1)
    all_p = {}

    cluster_nodes = set(S)
    not_in_cluster = set()
    for node in cluster_nodes:
        not_in_cluster |= neighbors[node]
    not_in_cluster -= cluster_nodes
    componente, n = componentes_del_cluster(neighbors, cluster_nodes)

    agregados = []
    pasos = []
    while True:
        #paso de proteinas: el candidato de p minimo entra solo si reduce la cantidad de componentes
        s0 = len(cluster_nodes)
        reducidos = reduce_not_in_cluster_nodes(componente, all_degrees, neighbors, cluster_nodes,
                                                not_in_cluster)
        mejor_nodo = _mejor(reducidos, N, s0, n, gamma_ln, all_p)
        nodo_reduce = False
        if mejor_nodo is not None and mejor_nodo[3] < umbral_p:
            nodo = mejor_nodo[0]
            cluster_nodes.add(nodo)
            componente_nuevo, m = componentes_del_cluster(neighbors, cluster_nodes)
            if m < n:
                nodo_reduce = True
                _, kb, k, p = mejor_nodo
                agregados.append((nodo, k, kb, p))
                pasos.append({"tipo": "proteina", "nodos": (nodo,), "kb": kb, "k": k,
                              "p": float(p), "componentes_antes": n, "componentes_despues": m})
                not_in_cluster = not_in_cluster | (neighbors[nodo] - cluster_nodes)
                not_in_cluster.remove(nodo)
                componente, n = componente_nuevo, m
                continue
            #no reduce: se revierte, igual que el original
            cluster_nodes.remove(nodo)

        #paso de interacciones, sobre el cluster y los vecinos de antes del nodo revertido
        s0 = len(cluster_nodes)
        reducidos = reduce_not_in_cluster_edges(componente, all_degrees, neighbors, cluster_nodes,
                                                not_in_cluster)
        mejor_arista = _mejor(reducidos, N, s0, n, gamma_ln, all_p)
        if mejor_arista is not None and mejor_arista[3] < umbral_p:
            (a, b), kb, k, p = mejor_arista
            cluster_nodes.add(a)
            cluster_nodes.add(b)
            componente_nuevo, m = componentes_del_cluster(neighbors, cluster_nodes)
            if m < n:
                agregados.append((a, k, kb, p))
                agregados.append((b, k, kb, p))
                pasos.append({"tipo": "interaccion", "nodos": (a, b), "kb": kb, "k": k,
                              "p": float(p), "componentes_antes": n, "componentes_despues": m})
                not_in_cluster |= (neighbors[a] - cluster_nodes)
                not_in_cluster |= (neighbors[b] - cluster_nodes)
                not_in_cluster.discard(a)
                not_in_cluster.discard(b)
                componente, n = componente_nuevo, m
                continue
            cluster_nodes.discard(a)
            cluster_nodes.discard(b)
            motivo = "la mejor proteina y la mejor interaccion no reducen componentes"
            arista_reduce = False
        else:
            motivo = "ninguna interaccion con p < umbral"
            arista_reduce = None

        motivo_corte = {
            "motivo": motivo,
            "componentes_finales": n,
            "mejor_proteina": _descripcion(mejor_nodo, nodo_reduce if mejor_nodo is not None
                                           and mejor_nodo[3] < umbral_p else None),
            "mejor_interaccion": _descripcion(mejor_arista, arista_reduce),
        }
        return agregados, pasos, motivo_corte


def C3(G_original, seed_genes, umbral_p=UMBRAL_P):
    """Corre C3 desde las semillas que estan en la red.

    Devuelve varios (agregados, pasos, motivo_corte):
    - agregados: [(nodo, k, kb, p), ...] en orden de agregado, el mismo contrato que DIAMOnD. Los dos extremos de una interaccion entran consecutivos con el k, kb y p de la arista.
    - pasos: un dict por paso aceptado (tipo proteina, nodos, kb, k, p y componentes antes y despues).
    - motivo_corte: por que paro, y el mejor nodo y la mejor arista del ultimo intento (reduce es None si no llegaron al umbral, False si llegaron pero no reducian).
    """
    all_genes_in_network = set(G_original.nodes())
    seed_genes = set(seed_genes)
    disease_genes = seed_genes & all_genes_in_network
    if len(disease_genes) != len(seed_genes):
        print(f"C3(): se descartan {len(seed_genes - all_genes_in_network)} semillas que no estan en la red")
    return c3_iteration(G_original, disease_genes, umbral_p)
