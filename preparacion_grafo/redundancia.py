"""Deteccion de nodos redundantes en una capa de OptimusKG: distintos identificadores que se refieren a la misma entidad. El grafo agrupa sus fuentes por prefijo CURIE y deduplica por nombre dentro de cada una, pero no cruza identificadores entre fuentes distintas, asi que cuando una fuente secundaria referencia una entidad con un identificador de otro espacio nace un segundo nodo con las aristas de esa fuente. Las funciones de este modulo son puras y no saben de Neo4j: reciben tablas ya traidas y devuelven pares candidatos. Las consultas viven en redundancia_entre_nodos.ipynb, que es donde se justifica cada señal."""
import hashlib
import re
import unicodedata

import pandas as pd

#los sufijos que dos ontologias usan indistintamente para el mismo concepto. no se quitan en el
#medio del nombre porque ahi si distinguen (celiac disease sin el sufijo queda en celiac, que no
#es un nombre)
SUFIJOS_INTERCAMBIABLES = ("disease", "disorder", "syndrome")

#lo que separa palabras y no aporta identidad. el apostrofe se borra en vez de volverse espacio
#para que hodgkin's lymphoma y hodgkins lymphoma caigan en la misma clave
_APOSTROFES = "'’ʼ`"
_SEPARADORES = re.compile(r"[^a-z0-9]+")


def normalizar(nombre):
    """Lleva un nombre a la clave con la que se lo compara: sin tildes, sin puntuacion, sin apostrofes, en minusculas, y sin el sufijo generico final que dos ontologias intercambian. Devuelve cadena vacia si el nombre es nulo o queda vacio."""
    if nombre is None or not isinstance(nombre, str):
        return ""
    sin_apostrofes = "".join(c for c in nombre if c not in _APOSTROFES)
    #NFKD separa la tilde de la vocal, y el filtro por categoria Mn la descarta
    descompuesto = unicodedata.normalize("NFKD", sin_apostrofes.lower())
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    palabras = [p for p in _SEPARADORES.split(sin_tildes) if p]
    if len(palabras) > 1 and palabras[-1] in SUFIJOS_INTERCAMBIABLES:
        palabras = palabras[:-1]
    return " ".join(palabras)


def normalizar_identificador(identificador):
    """Lleva un identificador a una forma comparable: MONDO:0007256 y MONDO_0007256 son el mismo nodo escrito con los dos separadores que conviven en el grafo."""
    if identificador is None or not isinstance(identificador, str):
        return ""
    return identificador.strip().replace(":", "_")


def grupos_por_clave(filas, columna_clave, columna_id="id", normalizador=None):
    """Agrupa los identificadores que comparten el valor de una columna y devuelve solo los grupos de dos o mas. Se hace en Python y no con collect() de Cypher porque collect descarta los nulos en silencio y desalinea las listas paralelas, que fue como se perdieron nodos al sondear la capa."""
    grupos = {}
    for fila in filas.to_dict("records") if isinstance(filas, pd.DataFrame) else filas:
        valor = fila.get(columna_clave)
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            continue
        clave = normalizador(valor) if normalizador else valor
        if clave == "" or clave is None:
            continue
        grupos.setdefault(clave, []).append(fila[columna_id])
    return {clave: sorted(set(ids)) for clave, ids in grupos.items() if len(set(ids)) > 1}


def pares_de_grupos(grupos):
    """Convierte los grupos en pares ordenados (a, b) con a menor que b, uno por combinacion dentro del grupo, con la clave que los junto como detalle. La salida se ordena para que los CSV sean reproducibles aunque los grupos lleguen en otro orden."""
    pares = []
    for clave, ids in grupos.items():
        ordenados = sorted(set(ids))
        for i, primero in enumerate(ordenados):
            for segundo in ordenados[i + 1:]:
                pares.append((primero, segundo, str(clave)))
    return sorted(pares)


def pares_por_sinonimo(nombres_por_id, sinonimos_por_id):
    """Empareja un nodo con otro cuando un sinonimo exacto del primero coincide con el nombre del segundo. Va contra un diccionario nombre a identificadores y no con un JOIN en Cypher: esa version es un producto cartesiano sin indice y no termino en dos minutos sobre la capa Disease."""
    ids_por_nombre = {}
    for identificador, nombre in nombres_por_id.items():
        clave = normalizar(nombre)
        if clave:
            ids_por_nombre.setdefault(clave, []).append(identificador)

    pares = []
    for identificador, sinonimos in sinonimos_por_id.items():
        for sinonimo in sinonimos or []:
            clave = normalizar(sinonimo)
            if not clave:
                continue
            for otro in ids_por_nombre.get(clave, []):
                if otro != identificador:
                    pares.append((min(identificador, otro), max(identificador, otro), sinonimo))
    return sorted(set(pares))


def pares_por_referencia(referencias_por_id, identificadores_existentes):
    """Empareja un nodo con otro cuando una de sus referencias cruzadas apunta a un identificador que existe como nodo de la misma capa. Los dos lados se normalizan porque el grafo mezcla los separadores : y _ en el mismo campo."""
    existentes = {normalizar_identificador(i): i for i in identificadores_existentes}
    pares = []
    for identificador, referencias in referencias_por_id.items():
        for referencia in referencias or []:
            apuntado = existentes.get(normalizar_identificador(referencia))
            if apuntado is None or apuntado == identificador:
                continue
            pares.append((min(identificador, apuntado), max(identificador, apuntado), referencia))
    return sorted(set(pares))


def pares_desde_sssom(mapeos, identificadores_existentes, predicado="skos:exactMatch"):
    """Saca de una tabla SSSOM los pares de identificadores que existen los dos como nodo de la capa, quedandose solo con el predicado pedido. Un mapeo hacia un vocabulario que no esta cargado no es un duplicado del grafo, por eso el filtro por existencia. Devuelve los pares ordenados y sin repetir."""
    existentes = {normalizar_identificador(i): i for i in identificadores_existentes}
    filas = mapeos[mapeos["predicate_id"] == predicado]
    pares = set()
    for sujeto, objeto in zip(filas["subject_id"], filas["object_id"]):
        a = existentes.get(normalizar_identificador(sujeto))
        b = existentes.get(normalizar_identificador(objeto))
        if a is None or b is None or a == b:
            continue
        pares.add((min(a, b), max(a, b)))
    return sorted(pares)


def unir_declarados(pares_por_fuente):
    """Cruza los pares declarados de varias fuentes en una tabla con un par por fila y una columna fuente que dice de cual salio, o ambas si salio de las dos. pares_por_fuente es un diccionario nombre a lista de pares (id_a, id_b)."""
    fuentes_por_par = {}
    for fuente, pares in pares_por_fuente.items():
        for a, b in pares:
            fuentes_por_par.setdefault((min(a, b), max(a, b)), set()).add(fuente)
    filas = [{"id_a": a, "id_b": b,
              "fuente": "ambas" if len(fuentes) > 1 else next(iter(fuentes))}
             for (a, b), fuentes in sorted(fuentes_por_par.items())]
    return pd.DataFrame(filas, columns=["id_a", "id_b", "fuente"])


def grupos_de_equivalencia(pares):
    """Arma los grupos de nodos equivalentes como componentes conexas del grafo de pares: si A es igual a B y B es igual a C, los tres son un solo grupo. Cada grupo y la lista de grupos van ordenados para que el resultado no dependa del orden de entrada."""
    vecinos = {}
    for a, b in pares:
        vecinos.setdefault(a, set()).add(b)
        vecinos.setdefault(b, set()).add(a)
    vistos, grupos = set(), []
    for inicio in sorted(vecinos):
        if inicio in vistos:
            continue
        #recorrido en anchura sin recursion, la componente mas grande medida tiene 14 nodos pero
        #no hay razon para depender de eso
        grupo, pendientes = set(), [inicio]
        while pendientes:
            nodo = pendientes.pop()
            if nodo in grupo:
                continue
            grupo.add(nodo)
            pendientes.extend(vecinos[nodo] - grupo)
        vistos |= grupo
        grupos.append(sorted(grupo))
    return sorted(grupos)


def hash_vecindario(vecinos):
    """Resume el vecindario de un nodo, dado como iterable de cadenas tipo relacion:id_vecino, en un hash que no depende del orden. Se hashea en vez de guardar el conjunto porque la capa Disease tiene diez millones de aristas y las listas completas no entran comodas en memoria."""
    unicos = sorted(set(vecinos))
    if not unicos:
        return ""
    #el separador no aparece en ningun tipo de relacion ni identificador de OptimusKG, asi que
    #dos vecindarios distintos no pueden producir la misma cadena
    return hashlib.sha1("|".join(unicos).encode("utf-8")).hexdigest()


def jaccard(primero, segundo):
    """Fraccion de vecinos compartidos sobre el total de vecinos distintos de los dos nodos. Devuelve 0 si los dos vecindarios estan vacios, que es el caso de dos nodos aislados, donde no hay evidencia de que sean el mismo."""
    a, b = set(primero), set(segundo)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def es_cascara(aristas_de_jerarquia, tipos_de_relacion):
    """Un nodo es cascara si no participa de la jerarquia de su capa y toda su vecindad viene de un solo tipo de relacion: el perfil de los nodos que aporta una fuente secundaria cuando referencia una entidad con un identificador de otro espacio."""
    return aristas_de_jerarquia == 0 and len(set(tipos_de_relacion)) <= 1


#orden de preferencia entre ontologias cuando todo lo demas empata. MONDO va primero porque es la
#ontologia que armoniza a las otras, o sea la que existe para ser el identificador unico de una
#enfermedad. el resto de los espacios caen al final con el mismo valor
PRIORIDAD_DE_ONTOLOGIA = {"MONDO": 0, "Orphanet": 1, "EFO": 2, "DOID": 3, "NCIT": 4}


def elegir_representante(grupo, grado, jerarquia):
    """Elige el nodo que representa a un grupo de nodos redundantes, con una cascada de cuatro criterios: mas aristas, mas aristas de jerarquia, ontologia de mayor prioridad, y el identificador menor. Los tres primeros son sustantivos y el ultimo esta solo para que el resultado no dependa del orden en que llegue el grupo. Elegir representante no es lo mismo que descartar a los demas: quien llama decide si las aristas del resto se arrastran o se pierden."""
    def clave(identificador):
        espacio = str(identificador).split("_")[0].split(":")[0]
        return (-grado.get(identificador, 0),
                -jerarquia.get(identificador, 0),
                PRIORIDAD_DE_ONTOLOGIA.get(espacio, len(PRIORIDAD_DE_ONTOLOGIA)),
                str(identificador))
    return min(grupo, key=clave)


def unir_senales(senales):
    """Cruza las listas de pares de cada señal en una tabla con una columna booleana por señal, el detalle de cada una y la cantidad de señales que marcaron ese par. Un par que aparece en dos señales independientes es un duplicado mas creible que uno que aparece en una sola, y por eso la tabla se ordena por esa cantidad. senales es un diccionario nombre a lista de tuplas (id_a, id_b, detalle)."""
    filas = {}
    for nombre, pares in senales.items():
        for id_a, id_b, detalle in pares:
            clave = (min(id_a, id_b), max(id_a, id_b))
            fila = filas.setdefault(clave, {"id_a": clave[0], "id_b": clave[1]})
            fila[nombre] = True
            #si la misma señal marca el par por mas de un motivo se conserva el primero, que
            #alcanza para rastrearlo a mano
            fila.setdefault(f"detalle_{nombre}", detalle)

    if not filas:
        columnas = ["id_a", "id_b"] + list(senales) + [f"detalle_{s}" for s in senales] + ["n_senales"]
        return pd.DataFrame(columns=columnas)

    tabla = pd.DataFrame(list(filas.values()))
    for nombre in senales:
        #las columnas se completan con False antes de convertir a bool y no con fillna sobre la
        #columna ya armada, que sobre dtype object dispara un FutureWarning de pandas por fila
        columna = tabla[nombre] if nombre in tabla else pd.Series([None] * len(tabla))
        tabla[nombre] = [bool(valor) if valor is not None and valor == valor else False
                         for valor in columna]
        if f"detalle_{nombre}" not in tabla:
            tabla[f"detalle_{nombre}"] = None
    tabla["n_senales"] = tabla[list(senales)].sum(axis=1)
    columnas = ["id_a", "id_b", "n_senales"] + list(senales) + [f"detalle_{s}" for s in senales]
    return tabla[columnas].sort_values(["n_senales", "id_a"], ascending=[False, True]).reset_index(drop=True)
