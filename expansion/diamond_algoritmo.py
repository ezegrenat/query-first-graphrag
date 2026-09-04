"""algoritmo DIAMOnD tomado del repositorio original de los autores:
(https://github.com/dinaghiassian/DIAMOnD,

Cuatro diferencias deliberadas contra el original:

1. logchoose en el original usa scipy.infty (removido en scipy >= 1.9).Aca se usa `np.inf`/`-np.inf` y se devuelve un escalar.
2. La entrada no es un archivo de edgelist: el grafo llega como networkx.Graph, ya construido desde Neo4j por el llamador.
3. Si la red se agota antes de agregar X nodos (es decir, no quedan candidatos), el original deja
   next_node = 'nix` y explota con KeyError al indexar info['nix']. Aca se corta el loop con un break explicito y se devuelve lo que se pudo agregar. no se cambia el resultado en
   ningun caso donde el original terminaba normalmente.

4. get_neighbors_and_degrees(G) en el original arma un diccionario de vecinos/grados para TODOS los nodos del grafo G de una. 
    Para aliviar el costo de memoria de calcular esto para todos los  odos de OptimusKG, lo que se hace en este caso es usar 
    un diccionario lazy (DictLiviano, más abajo) que permite que se calcule la primera vez que se pide y se VA cacheando, de esta 
    forma nunca cargamos nodos que el algoritmo no toca. 
    

"""
import numpy as np
import scipy.special


# =============================================================================
def compute_all_gamma_ln(N):
    """precomputa los logaritmos de gamma para 1..N (vectorizado con numpy en vez del loop
    python del original"""
    valores = scipy.special.gammaln(np.arange(1, N + 1))
    return {i: valores[i - 1] for i in range(1, N + 1)}


# =============================================================================
def logchoose(n, k, gamma_ln):
    #fuera de dominio C(n,k)=0, y log(0) = -inf: con el +inf del original, gauss_hypergeom
    #devolveria exp(+inf)=inf en vez de la probabilidad 0 que corresponde. k<0 tambien entra aca
    #porque gamma_ln se indexa desde 1 y gamma_ln[k+1] daria KeyError
    if k < 0 or n - k + 1 <= 0:
        return -np.inf
    lgn1 = gamma_ln[n + 1]
    lgk1 = gamma_ln[k + 1]
    lgnk1 = gamma_ln[n - k + 1]
    return lgn1 - (lgnk1 + lgk1)


# =============================================================================
def gauss_hypergeom(x, r, b, n, gamma_ln):
    return np.exp(logchoose(r, x, gamma_ln) +
                  logchoose(b, n - x, gamma_ln) -
                  logchoose(r + b, n, gamma_ln))


# =============================================================================
def pvalue(kb, k, N, s, gamma_ln):
    """
    -------------------------------------------------------------------
    Computes the p-value for a node that has kb out of k links to
    seeds, given that there's a total of s sees in a network of N nodes.

    p-val = \\sum_{n=kb}^{k} HypergemetricPDF(n,k,N,s)
    -------------------------------------------------------------------
    (docstring del calculo, igual al original)
    """
    p = 0.0
    for n in range(kb, k + 1):
        if n > s:
            break
        p += gauss_hypergeom(n, s, N - s, k, gamma_ln)

    if p > 1:
        return 1.0
    return p


class _DictLiviano:
    """Dict de solo lectura que calcula cada valor la primera vez que se pide y
    lo cachea para no precalcular neighbors/all_degrees de nodos que el algoritmo nunca va
    a visitar en redes grandes. Más allá de eso, todo es identico a lo que se 
    usa el resto del algoritmo."""

    def __init__(self, funcion):
        self._funcion = funcion
        self._cache = {}

    def __getitem__(self, nodo):
        if nodo not in self._cache:
            self._cache[nodo] = self._funcion(nodo)
        return self._cache[nodo]


# =============================================================================
def get_neighbors_and_degrees(G):
    neighbors, all_degrees = {}, {}
    for node in G.nodes():
        nn = set(G.neighbors(node))
        neighbors[node] = nn
        all_degrees[node] = G.degree(node)

    return neighbors, all_degrees


# =============================================================================
# Reduce number of calculations
# =============================================================================
def reduce_not_in_cluster_nodes(all_degrees, neighbors, G, not_in_cluster, cluster_nodes, alpha):
    reduced_not_in_cluster = {}
    kb2k = {}
    for node in not_in_cluster:
        k = all_degrees[node]
        kb = 0
        # Going through all neighbors and counting the number of module neighbors
        for neighbor in neighbors[node]:
            if neighbor in cluster_nodes:
                kb += 1

        # adding wights to the the edges connected to seeds
        k += (alpha - 1) * kb
        kb += (alpha - 1) * kb
        kb2k.setdefault(kb, {})[k] = node

    # Going to choose the node with largest kb, given k
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


# ======================================================================================
#   C O R E    A L G O R I T H M
# ======================================================================================
def diamond_iteration_of_first_X_nodes(G, S, X, alpha):
    """
    Parameters:
    ----------
    - G:     graph
    - S:     seeds
    - X:     the number of iterations, i.e only the first X gened will be
             pulled in
    - alpha: seeds weight
    Returns:
    --------

    - added_nodes: ordered list of nodes in the order by which they
      are agglomerated. Each entry has 4 info:
      * name : dito
      * k    : degree of the node
      * kb   : number of +1 neighbors
      * p    : p-value at agglomeration
    """

    N = G.number_of_nodes()

    added_nodes = []

    # ------------------------------------------------------------------
    # Setting up dictionaries with all neighbor lists
    # and all degrees
    # ------------------------------------------------------------------

    neighbors = _DictLiviano(lambda nodo: set(G.neighbors(nodo)))
    all_degrees = _DictLiviano(G.degree)

    # ------------------------------------------------------------------
    # Setting up initial set of nodes in cluster
    # ------------------------------------------------------------------

    cluster_nodes = set(S)
    not_in_cluster = set()
    s0 = len(cluster_nodes)

    s0 += (alpha - 1) * s0
    N += (alpha - 1) * s0

    # ------------------------------------------------------------------
    # precompute the logarithmic gamma functions
    # ------------------------------------------------------------------
    gamma_ln = compute_all_gamma_ln(int(N) + 1)

    # ------------------------------------------------------------------
    # Setting initial set of nodes not in cluster
    # ------------------------------------------------------------------
    for node in cluster_nodes:
        not_in_cluster |= neighbors[node]
    not_in_cluster -= cluster_nodes

    # ------------------------------------------------------------------
    #
    # M A I N     L O O P
    #
    # ------------------------------------------------------------------

    all_p = {}

    while len(added_nodes) < X:

        # ------------------------------------------------------------------
        #
        # Going through all nodes that are not in the cluster yet and
        # record k, kb and p
        #
        # ------------------------------------------------------------------

        info = {}

        pmin = 10
        next_node = None
        reduced_not_in_cluster = reduce_not_in_cluster_nodes(all_degrees,
                                                               neighbors, G,
                                                               not_in_cluster,
                                                               cluster_nodes, alpha)

        for node, kbk in reduced_not_in_cluster.items():
            # Getting the p-value of this kb,k
            # combination and save it in all_p, so computing it only once!
            kb, k = kbk
            try:
                p = all_p[(k, kb, s0)]
            except KeyError:
                p = pvalue(kb, k, N, s0, gamma_ln)
                all_p[(k, kb, s0)] = p

            # recording the node with smallest p-value
            if p < pmin:
                pmin = p
                next_node = node

            info[node] = (k, kb, p)

        if next_node is None:
            # no quedan candidatos (red agotada) -- corta antes de llegar a X
            break

        # ---------------------------------------------------------------------
        # Adding node with smallest p-value to the list of aaglomerated nodes
        # ---------------------------------------------------------------------
        added_nodes.append((next_node,
                             info[next_node][0],
                             info[next_node][1],
                             info[next_node][2]))

        # Updating the list of cluster nodes and s0
        cluster_nodes.add(next_node)
        s0 = len(cluster_nodes)
        not_in_cluster |= (neighbors[next_node] - cluster_nodes)
        not_in_cluster.remove(next_node)

    return added_nodes


# ===========================================================================
#
#   M A I N    D I A M O n D    A L G O R I T H M
#
# ===========================================================================
def DIAMOnD(G_original, seed_genes, max_number_of_added_nodes, alpha=1, outfile=None):
    """
    Runs the DIAMOnD algorithm
    Input:
    ------
     - G_original :
             The network
     - seed_genes :
             a set of seed genes
     - max_number_of_added_nodes:
             after how many added nodes should the algorithm stop
     - alpha:
             given weight to the sees
     - outfile:
             filename for the output generates by the algorithm,
             if not given no file is written (el original siempre escribia; aca es opcional
             porque quien llama suele loguear por su cuenta)
     Returns:
     --------
      - added_nodes: A list with 4 entries at each element:
            * name : name of the node
            * k    : degree of the node
            * kb   : number of neighbors that are part of the module (at agglomeration)
            * p    : connectivity p-value at agglomeration
    """

    # 1. throwing away the seed genes that are not in the network
    all_genes_in_network = set(G_original.nodes())
    seed_genes = set(seed_genes)
    disease_genes = seed_genes & all_genes_in_network

    if len(disease_genes) != len(seed_genes):
        print("DIAMOnD(): ignorando %s de %s semillas que no estan en la red" % (
            len(seed_genes - all_genes_in_network), len(seed_genes)))

    # 2. agglomeration algorithm.
    added_nodes = diamond_iteration_of_first_X_nodes(G_original,
                                                       disease_genes,
                                                       max_number_of_added_nodes, alpha)
    # 3. saving the results (opcional)
    if outfile is not None:
        with open(outfile, 'w') as fout:
            fout.write('\t'.join(['#rank', 'DIAMOnD_node', 'p_hyper']) + '\n')
            for rank, nodo in enumerate(added_nodes, start=1):
                fout.write('\t'.join(map(str, (rank, nodo[0], float(nodo[3])))) + '\n')

    return added_nodes
