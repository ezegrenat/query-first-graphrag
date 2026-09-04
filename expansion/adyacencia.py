"""Adyacencia de un subgrafo de OptimusKG, acotado por tipos de nodo y de relacion, en una representacion que entra en memoria con millones de aristas.

"""
import time

import numpy as np
from scipy import sparse


class RedCompacta:
    def __init__(self, matriz, ids):
        self._matriz = matriz.tocsr()
        self._ids = np.asarray(ids)
        self._indice_por_id = {v: i for i, v in enumerate(self._ids)}
        self.n_nodos = len(self._ids)
        self.n_aristas = int(self._matriz.nnz // 2)
        self.grados = _Grados(self)

    def get(self, id_nodo, default=()):
        """Vecinos de un nodo, por su id real. La firma imita a dict.get para que el algoritmo de DIAMOnD no tenga que enterarse de que abajo hay una matriz dispersa."""
        i = self._indice_por_id.get(id_nodo)
        if i is None:
            return default
        desde, hasta = self._matriz.indptr[i], self._matriz.indptr[i + 1]
        return self._ids[self._matriz.indices[desde:hasta]]

    def grado(self, id_nodo):
        i = self._indice_por_id.get(id_nodo)
        if i is None:
            return 0
        return int(self._matriz.indptr[i + 1] - self._matriz.indptr[i])

    def __contains__(self, id_nodo):
        return id_nodo in self._indice_por_id

    def __iter__(self):
        return iter(self._ids)


    #alias con la interfaz de networkx.Graph (nodes/neighbors/degree/number_of_nodes). los pide Diamond_algoritmo.py
    def nodes(self):
        return self._ids

    def neighbors(self, id_nodo):
        return self.get(id_nodo, ())

    def degree(self, id_nodo):
        return self.grado(id_nodo)

    def number_of_nodes(self):
        return self.n_nodos

    def number_of_edges(self):
        return self.n_aristas

    def __len__(self):
        return self.n_nodos

    def memoria_mb(self):
        m = self._matriz
        return (m.data.nbytes + m.indices.nbytes + m.indptr.nbytes) / 1024 / 1024

    def guardar(self, ruta):
        """Persiste la red a disco (ruta.npz para la matriz CSR, ruta_ids.npy para los ids reales) para no repetir la extraccion de Neo4j cuando no cambio nada del lado de la base"""
        sparse.save_npz(f"{ruta}.npz", self._matriz)
        np.save(f"{ruta}_ids.npy", self._ids, allow_pickle=True)

    @staticmethod
    def cargar(ruta):
        """Inversa de guardar. allow_pickle=True porque los ids son un array de strings de Python (dtype object) y no un tipo numerico nativo de numpy. Son archivos que genera este mismo repo, asi que deserializarlos tiene el mismo riesgo que correr cualquier otro script de aca."""
        matriz = sparse.load_npz(f"{ruta}.npz")
        ids = np.load(f"{ruta}_ids.npy", allow_pickle=True)
        return RedCompacta(matriz, ids)


class _Grados:
    """Vista de solo lectura de los grados, con la interfaz de dict que usa diamond_expand."""

    def __init__(self, red):
        self._red = red

    def get(self, id_nodo, default=0):
        return self._red.grado(id_nodo) or default

    def __getitem__(self, id_nodo):
        return self._red.grado(id_nodo)

    def __len__(self):
        return self._red.n_nodos


def construir_red(gds, tipos_de_nodo, tipos_de_relacion, tamano_lote=20_000, verbose=True,
                   evidencia_minima=None, pares_estrictos=False, filtro_cypher=None):
    """Trae del grafo las aristas entre nodos de tipos_de_nodo cuya relacion este en tipos_de_relacion, y las devuelve como RedCompacta.

    Los dos extremos tienen que ser de alguno de los tipos pedidos: por ej pedir ["Gene"] con ["INTERACTS_WITH"] da el interactoma, y pedir varios tipos junta todas las aristas internas de esa union de tipos. Los nombres de tipo y de relacion se interpolan en el Cypher porque Neo4j no deja parametrizarlos, asi que antes se valida que sean identificadores.

    tamano_lote es el ancho del rango de ids internos que se pide por consulta.
    
    evidencia_minima: si no es None, descarta las aristas ASSOCIATED_WITH con r.evidence_score menor a ese valor.
    
    pares_estrictos: con True hacen falta exactamente 2 tipos distintos en tipos_de_nodo, y se exige que un extremo sea de uno y el otro extremo del otro, lo que excluye por construccion cualquier arista homogenea (mismo tipo en los dos extremos) sin importar en que direccion la haya guardado Neo4j. Hace falta cuando el mismo nombre de relacion se reusa para una arista homogenea y una heterogenea

    filtro_cypher: predicado extra sobre la relacion r en Cypher que se agrega al WHERE como AND (filtro_cypher)

"""
    for nombre in list(tipos_de_nodo) + list(tipos_de_relacion):
        if not nombre.replace("_", "").isalnum():
            raise ValueError(f"nombre de tipo inválido: {nombre!r}")

    if pares_estrictos:
        distintos = list(dict.fromkeys(tipos_de_nodo))  #unicos, preservando orden
        if len(distintos) != 2:
            raise ValueError(
                f"pares_estrictos=True necesita exactamente 2 tipos distintos, mientras que hay {distintos}")
        t1, t2 = distintos
        condicion_tipos = f"((a:{t1} AND b:{t2}) OR (a:{t2} AND b:{t1}))"
    else:
        etiquetas = " OR ".join(f"a:{t}" for t in tipos_de_nodo)
        etiquetas_b = " OR ".join(f"b:{t}" for t in tipos_de_nodo)
        condicion_tipos = f"({etiquetas}) AND ({etiquetas_b})"
    relaciones = "|".join(tipos_de_relacion)
    filtro_evidencia = ""
    if evidencia_minima is not None:
        filtro_evidencia = (
            " AND (type(r) <> 'ASSOCIATED_WITH' OR r.evidence_score >= $evidencia_minima)"
        )
    filtro_extra = f" AND ({filtro_cypher})" if filtro_cypher else ""

    t0 = time.time()
    #se trae por lotes, particionando por rango de id(a)
    id_maximo = int(gds.run_cypher("MATCH (n) RETURN max(id(n)) AS m")["m"].iloc[0])
    filas_a, filas_b = [], []
    total = 0
    params_base = {}
    if evidencia_minima is not None:
        params_base["evidencia_minima"] = evidencia_minima
    for desde in range(0, id_maximo + 1, tamano_lote):
        lote = gds.run_cypher(
            f"MATCH (a)-[r:{relaciones}]->(b) "
            f"WHERE id(a) >= $desde AND id(a) < $hasta "
            f"AND {condicion_tipos} AND id(a) <> id(b)"
            f"{filtro_evidencia}{filtro_extra} "
            f"RETURN id(a) AS a, id(b) AS b",
            params={"desde": desde, "hasta": desde + tamano_lote, **params_base},
        )
        if len(lote):
            filas_a.append(lote["a"].to_numpy(dtype=np.int64))
            filas_b.append(lote["b"].to_numpy(dtype=np.int64))
            total += len(lote)
        del lote

    if verbose:
        print(f"aristas traidas: {total:,} en {id_maximo // tamano_lote + 1} lotes "
              f"({time.time()-t0:.1f}s)")
    if total == 0:
        raise ValueError(f"ninguna arista {tipos_de_relacion} entre nodos {tipos_de_nodo}")

    origen = np.concatenate(filas_a)
    destino = np.concatenate(filas_b)
    del filas_a, filas_b
    internos = np.unique(np.concatenate([origen, destino]))
    posicion = {v: i for i, v in enumerate(internos)}
    fila = np.fromiter((posicion[v] for v in origen), dtype=np.int32, count=len(origen))
    columna = np.fromiter((posicion[v] for v in destino), dtype=np.int32, count=len(destino))
    del origen, destino

    n = len(internos)
    matriz = sparse.csr_matrix((np.ones(len(fila), dtype=np.int8), (fila, columna)), shape=(n, n))
    #simetrizar y binarizar: DIAMOnD trabaja sobre un grafo no dirigido y sin multiaristas, asi
    #que dos relaciones entre el mismo par (o la misma en los dos sentidos) tienen que contar como
    #una sola
    matriz = matriz + matriz.T #una arista dirigida a->b vale tambien b -> a 
    matriz.data[:] = 1
    matriz.setdiag(0)
    matriz.eliminate_zeros()

    #se traen los ids reales uno por nodo 
    ids_reales = gds.run_cypher(
        "UNWIND $internos AS interno MATCH (n) WHERE id(n) = interno RETURN id(n) AS interno, n.id AS id",
        params={"internos": internos.tolist()},
    ).set_index("interno").loc[internos, "id"].to_numpy()

    red = RedCompacta(matriz, ids_reales)
    if verbose:
        print(f"red compacta: {red.n_nodos:,} nodos, {red.n_aristas:,} aristas, "
              f"{red.memoria_mb():.1f}MB ({red.memoria_mb()*1024*1024/max(red.n_aristas,1):.1f} "
              f"bytes/arista)")
    return red
