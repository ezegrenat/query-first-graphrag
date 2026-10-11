
1. Introducción

1.1 Propósito

Este documento especifica el módulo que selecciona el subgrafo de una query. Dado un conjunto de entidades ya identificadas en el grafo, se proyecta cada una a las capas donde tiene vecinos, se unen las proyecciones y se devuelve el subgrafo que inducen en el grafo original todos los nodos seleccionados.

Define los requisitos del módulo, sus estructuras de datos y la interfaz de cada función. Sirve para escribir el código a partir de él y para que quien lea el código entienda qué hace cada parte y por qué.

1.2 Alcance

Incluye:

- La proyección de una entidad por cada uno de los pasos de su tipo: cosecha de vecinos y expansión dentro de un plano con DIAMOnD, C3 o DIAMOnD k + C3.
- La unión de las proyecciones de una o varias entidades, con la procedencia de cada nodo.
- El armado del subgrafo inducido a partir de Neo4j.

No incluye:

- El entity matching. Las entidades llegan como nodos del grafo (label e id), y pasar de texto a nodo es una etapa anterior.
- Las comunidades, los resúmenes y todo lo que GraphRAG hace después con el subgrafo.

1.3 Definiciones

Entidad: un nodo de la query, identificado por el par (label, id).

Plano: la red homogénea de un tipo de nodo, donde corre DIAMOnD. Son tres: gene (relación PPI), disease (DISEASE_DISEASE, sin grupos BERT) y drug (DRUG_DRUG desde un umbral).

Paso: ir de una entidad de tipo A al plano B, por ejemplo disease_a_gene. Es la misma unidad que la calibración llama celda.

Cosecha: los vecinos de tipo B de la entidad, por la relación del paso (GDA, INDICATION o DRUG_TARGET).

Semillas: los vecinos cosechados que están en el plano B. Son los únicos con los que puede arrancar DIAMOnD.

Proyección: lo que produce un paso para una entidad, es decir, la cosecha más los nodos que agregó la expansión.

Procedencia: el registro de qué entidad y qué paso trajeron a un nodo, y con qué rol.

Selección: el conjunto de nodos de la query, cada uno con todas sus procedencias, todavía sin aristas.

Subgrafo inducido: los nodos de la selección más todas las aristas del grafo original cuyos dos extremos están en ella.

1.4 Referencias

- manipulacion_grafo/planos_y_pasos.py y expansion/, en el repo público (~/tesis/repositorio): el código que se reutiliza (sección 2.3).
- calibracion/resultados/: casos.csv y los parquet por caso, que son la referencia de lo que tiene que dar cada paso.
- Ghiassian, Menche y Barabási (2015): el paper de DIAMOnD.


2. Descripción general

2.1 Contexto

El módulo es la etapa de recuperación del pipeline de GraphRAG. Recibe las entidades que identificó el entity matching y le entrega el subgrafo a la etapa de comunidades y resúmenes. El criterio de selección es topológico: no usa el texto de los nodos ni embeddings.

El grafo es PrimeKG integrado más la capa de drogas, cargado en neo4j-thesis. Los tipos son Disease, Gene y Drug, y los planos y los pasos son los mismos de manipulacion_grafo/planos_y_pasos.py, que también usa la calibración.

2.2 Flujo

    entidades
       |
       v
    proyectar_heterogeneo      una vez por entidad
       |     (adentro, proyectar: una vez por paso de la entidad)
       v
    unir                       de proyecciones a selección con procedencias
       |
       v
    refinar
       |
       v
    materializar_subgrafo      de selección a subgrafo inducido, desde Neo4j

La función obtener_subgrafo_query encadena las cuatro etapas. cargar_grafo se llama una vez, antes.

2.3 Dependencias

- El contenedor neo4j-thesis levantado, con la capa de drogas cargada. Lo usan la cosecha y el subgrafo inducido.
- manipulacion_grafo/planos_y_pasos.py: PLANOS, CELDAS (los pasos, con su origen, plano y relación de cosecha), plano_drug, obtener_plano, conectar, MIN_SEMILLAS y UMBRAL_DRUG_MINIMO. Es el mismo módulo que usa la calibración.
- expansion/: RedCompacta y un .py por método de expansión: diamond_algoritmo.py (el port de DIAMOnD, sin cambios), c3_algoritmo.py (el port de C3) y diamond_c3_algoritmo.py (DIAMOnD k iteraciones y después C3 desde las semillas más lo agregado). Los tres devuelven los agregados como tuplas (nodo, k, kb, p) en orden de agregado; C3 y DIAMOnD_C3 devuelven además los pasos y el motivo de corte de C3.
- Python 3.12 con las dependencias de requirements.txt, en la raíz del repositorio. Es el mismo entorno de la calibración.


2.4 Supuestos y restricciones

- Las entidades que llegan existen en el grafo y son de tipo Disease, Gene o Drug.
- Solo se usan los seis pasos cruzados. Los de mismo tipo (de A a A) quedan afuera

- En Neo4j, las aristas DRUG_DRUG del laboratorio arrancan en similaridad 0,81. Con el umbral de 0,8 el plano drug las tiene todas, y no se puede armar con un umbral menor.
- Todavía no hay un corte de iteraciones decidido para el método "diamond". La calibración corrió con presupuesto fijo en 100. Para "diamond_c3" hay un k por paso elegido por la meseta del recall (K_POR_PASO en planos_y_pasos.py, 2026-09-25), que se puede pasar como iter_por_paso.


3. Modelo de datos

Los nodos se identifican por el par (label, id) y no por el id solo, para no depender de que los ids de distintos tipos nunca coincidan.

3.1 Grafo

Lo que devuelve cargar_grafo y reciben las demás funciones.

- gds (GraphDataScience): la conexión a neo4j-thesis.
- planos (dict de str a RedCompacta): los planos gene, disease y drug, ya cargados.
- umbral_drug (float): el corte con el que se armó el plano drug.

3.2 Procedencia

Inmutable. Dice por qué un nodo está en la selección.

- entidad (tuple[str, str]): el (label, id) de la entidad de la query que trajo el nodo.
- paso (str o None): el nombre del paso. None para la propia entidad.
- rol (str): uno de "entidad", "semilla", "vecino_fuera_del_plano" o "agregado".
- iteracion (int o None): para el rol "agregado", en qué posición de la expansión entró, contando desde 1. En "diamond_c3" la numeración sigue de corrido: primero los de DIAMOnD y después los de C3.
- p_valor (float o None): para el rol "agregado", el p-valor con el que entró.
- metodo (str o None): para el rol "agregado", el algoritmo que lo agregó, "diamond" o "c3". None en los demás roles.

3.3 Proyeccion

- entidad (tuple[str, str]).
- paso (str o None): None en la proyección trivial de la entidad.
- nodos (dict de (label, id) a lista de Procedencia).
- expandio (bool): False si no corrió la expansión.

3.4 Seleccion

Un diccionario de (label, id) a lista de Procedencia: los nodos con todas sus procedencias, sin aristas.

3.5 Subgrafo

- nodos (DataFrame): columnas label, id, nombre y procedencias.
- aristas (DataFrame): columnas label_a, id_a, label_b, id_b, tipo y propiedades (el weight, por ejemplo).

Las proyecciones no devuelven aristas: se calculan una sola vez, al final, como subgrafo inducido. Así aparecen también las aristas entre módulos de capas distintas, como un GDA entre un gen agregado y una enfermedad agregada, que ninguna proyección ve por separado.


4. Interfaces

Todas las funciones que reciben el grafo lo reciben como primer parámetro, con el nombre G.

4.1 cargar_grafo(umbral_drug=0.8) -> Grafo

Abre la conexión a Neo4j y carga los tres planos una sola vez, con obtener_plano y su caché. El umbral del plano drug entra acá porque cambia la red.

Parámetros:
- umbral_drug (float, por defecto 0,8): similaridad mínima de una arista DRUG_DRUG para entrar al plano drug.

Retorna: un Grafo con la conexión abierta, los tres planos como RedCompacta y el umbral usado.

Precondiciones: neo4j-thesis está levantado y tiene la capa de drogas cargada.

Errores posibles: ValueError si umbral_drug es menor que 0,8. Error de conexión si Neo4j no responde.

4.2 proyectar(G, entidad, paso, n_iter, min_semillas=MIN_SEMILLAS, metodo="diamond") -> Proyeccion

Corre un paso para una entidad. Equivale a un caso de la calibración.

  1. Cosecha los vecinos de tipo B de la entidad con la relación del paso. La consulta es por entidad (WHERE a.id = $id), a diferencia de la calibración, que trae todas las entidades juntas.
  2. Los separa en semillas, que están en el plano B, y vecinos fuera del plano. Los dos grupos entran a la proyección, cada uno con su rol.
  3. Si hay al menos min_semillas semillas y n_iter es mayor que 0, expande en el plano B con esas semillas según metodo, y suma cada nodo agregado con su posición, su p-valor y el algoritmo que lo agregó. Si no, devuelve solo la cosecha, con expandio en False.

  Los métodos:
  - "diamond": DIAMOnD con n_iter iteraciones. Es el comportamiento anterior al parámetro.
  - "c3": C3 desde las semillas, hasta que ningún nodo ni arista reduce las componentes. n_iter no es un presupuesto, solo tiene que ser mayor que 0 para que el paso expanda.
  - "diamond_c3": DIAMOnD con n_iter iteraciones y después C3 desde las semillas más lo que agregó DIAMOnD.

No incluye a la entidad. De eso se ocupa proyectar_heterogeneo.

Parámetros:
- G (Grafo): lo que devuelve cargar_grafo.
- entidad (tuple[str, str]): el (label, id) de un nodo que existe en el grafo.
- paso (str): el nombre de uno de los seis pasos, por ejemplo disease_a_gene.
- n_iter (int): cuántos nodos agrega DIAMOnD como máximo (en "c3", cualquier valor mayor que 0). Con 0 no se expande.
- min_semillas (int, por defecto MIN_SEMILLAS, que vale 5): con menos semillas en el plano no se expande.
- metodo (str, por defecto "diamond"): uno de METODOS, "diamond", "c3" o "diamond_c3".

Retorna: una Proyeccion con la entidad y el paso tal como entraron. En nodos están los vecinos cosechados, con rol "semilla" o "vecino_fuera_del_plano", y los nodos que agregó la expansión, con rol "agregado", su posición, su p-valor y su metodo. El campo expandio es True si corrió la expansión.

Precondiciones: el origen del paso es el label de la entidad.

Postcondiciones: todos los nodos son del tipo del plano y cada uno tiene una sola procedencia. La entidad no está entre ellos. Con "diamond" los agregados son a lo sumo n_iter, y pueden ser menos si la red se agota antes; con "c3" y "diamond_c3" C3 no tiene tope. Si la entidad no tiene vecinos por ese paso, nodos queda vacío.

Errores: ValueError si el metodo no es uno de METODOS, si el paso no existe, si su origen no es el label de la entidad, si la entidad no está en el grafo o si n_iter es negativo.

4.3 proyectar_heterogeneo(G, entidad, iter_por_paso, min_semillas=MIN_SEMILLAS, metodo="diamond") -> list[Proyeccion]

Corre proyectar en cada paso cuyo origen es el tipo de la entidad y en el que la entidad tiene al menos un vecino cosechado. Un paso que no figura en iter_por_paso corre con n_iter en 0 y aporta solo el vecindario. Además devuelve una proyección trivial con la entidad sola (rol "entidad"), para que una entidad sin vecinos igual quede en el resultado.

El diccionario iter_por_paso va por paso y no por capa destino. Los pasos disease_a_gene y drug_a_gene expanden en el mismo plano, pero en la calibración se comportan distinto, y en una query con entidades de tipos distintos un diccionario por capa sería ambiguo.

Parámetros:
- G (Grafo).
- entidad (tuple[str, str]): el (label, id) de un nodo que existe en el grafo.
- iter_por_paso (dict de str a int): de nombre de paso a n_iter, por ejemplo disease_a_gene en 100 y disease_a_drug en 20. Puede traer pasos de otros tipos de origen, que para esta entidad se ignoran.
- min_semillas (int, por defecto MIN_SEMILLAS): se le pasa tal cual a proyectar.
- metodo (str, por defecto "diamond"): se le pasa tal cual a proyectar, el mismo en todos los pasos.

Retorna: una lista de Proyeccion. Primero va la proyección trivial, con paso en None, expandio en False y la entidad como único nodo, y después una por cada paso con vecinos, en el orden de CELDAS.

Postcondiciones: la lista nunca está vacía. Para una entidad sin vecinos tiene solo la trivial.

Errores: ValueError si la entidad no está en el grafo o si iter_por_paso nombra un paso que no existe.

4.4 unir(proyecciones) -> Seleccion

Junta cualquier lista de proyecciones, de una entidad o de varias, en un solo diccionario de nodos. Si un nodo aparece en más de una proyección, se concatenan sus procedencias y no se descarta ninguna.

Si dos entidades distintas traen el mismo nodo, queda registrado, y el criterio para combinar módulos se puede decidir después sin volver a correr nada.

Parámetros:
- proyecciones (list[Proyeccion]): salidas de proyectar o de proyectar_heterogeneo, de una entidad o de varias. Puede estar vacía.

Retorna: una Seleccion, o sea un diccionario de (label, id) a la lista de todas las procedencias de ese nodo.

Postcondiciones: es conmutativa y asociativa, y unir una sola proyección no la cambia. Una lista vacía da un diccionario vacío.

Errores: ninguno propio. No consulta Neo4j.

4.5 refinar(G, seleccion) -> Seleccion

Parámetros:
- G (Grafo).
- seleccion (Seleccion): la salida de unir.

Retorna: una Seleccion.

Postcondiciones: cuando se implemente, puede agregar nodos con un rol nuevo, pero no sacar ninguno de los que entraron.

4.6 materializar_subgrafo(G, seleccion) -> Subgrafo

Arma el subgrafo inducido en el grafo original. Los nodos son exactamente los de la selección, con su nombre y sus procedencias. Las aristas son todas las del grafo cargado en Neo4j cuyos dos extremos están en la selección, de cualquier relación, con su tipo y sus propiedades, y ninguna aparece dos veces.

Como no se filtra por relación, si entró un grupo BERT entran también sus DISEASE_BERT hacia los miembros que estén en la selección, y si no entró, no pasa nada. Lo mismo vale para FORM_COMPLEX, que no está en el plano gene pero sí en el grafo.

Consulta de referencia. El código usa otra que devuelve lo mismo, con una rama por label para poder usar el índice de id, porque esta tarda unos 30 segundos con 350 nodos y aquella 0,3:

    UNWIND $pares AS p
    MATCH (a) WHERE p.label IN labels(a) AND a.id = p.id
    WITH collect(a) AS sel
    UNWIND sel AS a
    MATCH (a)-[r]-(b)
    WHERE b IN sel AND elementId(a) < elementId(b)
    RETURN a, type(r) AS tipo, properties(r) AS props, b

Parámetros:
- G (Grafo): se usa solo la conexión, no los planos.
- seleccion (Seleccion): la salida de unir o de refinar.

Retorna: un Subgrafo con dos DataFrames. El de nodos tiene una fila por nodo de la selección, con label, id, nombre y procedencias. El de aristas tiene una fila por arista, con label_a, id_a, label_b, id_b, tipo y propiedades, que es un diccionario con lo que traiga la relación (el weight en DRUG_DRUG).

Postcondiciones: nodos tiene tantas filas como nodos la selección. Una selección vacía da dos DataFrames vacíos con esas columnas.

Errores: ValueError si algún nodo de la selección no está en Neo4j.

4.7 obtener_subgrafo_query(G, entidades, iter_por_paso, min_semillas=MIN_SEMILLAS, metodo="diamond") -> Subgrafo

Es la entrada del módulo. Encadena las etapas de la sección 2.2:

    proyecciones = [p for e in entidades
                    for p in proyectar_heterogeneo(G, e, iter_por_paso, min_semillas, metodo)]
    return materializar_subgrafo(G, refinar(G, unir(proyecciones)))

No hace falta una función obtener_subgrafo_entidad aparte, porque es esta misma con una lista de una sola entidad.

Parámetros:
- G (Grafo).
- entidades (list[tuple[str, str]]): los (label, id) de las entidades de la query, de cualquier mezcla de tipos. Las repetidas se cuentan una sola vez.
- iter_por_paso (dict de str a int): el mismo diccionario para todas las entidades. Cada una usa los pasos de su tipo.
- min_semillas (int, por defecto MIN_SEMILLAS).
- metodo (str, por defecto "diamond"): el mismo para todas las entidades y todos los pasos.

Retorna: el Subgrafo de la query, con el formato de materializar_subgrafo.

Postcondiciones: las entidades están siempre entre los nodos, con rol "entidad".

Errores: los de proyectar_heterogeneo y materializar_subgrafo.


5. Casos borde

Entidad sin vecinos de ningún tipo. El subgrafo tiene un solo nodo, la entidad, y ninguna arista.

Entidad con menos de min_semillas semillas en un plano. Ese paso aporta solo el vecindario, con expandio en False.

Vecino cosechado que no está en el plano. Entra a la selección con rol "vecino_fuera_del_plano" y no siembra.

La red se agota antes de n_iter. Los agregados son menos que n_iter y no es un error. Ya pasó en el plano drug durante la calibración.

Dos entidades de la query donde una es vecina de la otra. Ese nodo aparece una sola vez, con dos procedencias: una con rol "entidad" y otra con rol "semilla" o "vecino_fuera_del_plano".

El mismo nodo traído por dos entidades o por dos pasos. Una sola fila en nodos, con todas sus procedencias.

La entidad es un grupo BERT. Se cosecha desde el grupo, sin el filtro de entidad de la calibración. Llega a sus drogas por INDICATION (hay 876 aristas a grupos) y a ningún gen, porque los grupos no tienen GDA.

Lista de entidades vacía. Subgrafo vacío, con las columnas definidas.


6. Consideraciones de diseño

Usar el subgrafo inducido completo tiene tres consecuencias.

DRUG_DRUG entra entera, porque en Neo4j están cargados todos los pares de similaridad 0,81 o más. Si el plano drug se corre con un umbral mayor que 0,8, el inducido igual trae las aristas por debajo de ese umbral entre las drogas seleccionadas. El weight viaja en las propiedades, y se puede filtrar en la etapa siguiente si hace falta.

El tamaño lo controla iter_por_paso. Una enfermedad expande hacia gene y hacia drug, y su selección tiene la cosecha más hasta dos veces n_iter nodos. Cuántas aristas trae el inducido depende de lo denso que sea el grafo entre esos nodos, sobre todo en el PPI.

Los pathways no entran nunca, porque ningún paso los selecciona.


7. Asuntos abiertos

A-01. El criterio de corte por paso. Hasta que se decida, los valores de iter_por_paso son arbitrarios para "diamond"; para "diamond_c3" está K_POR_PASO.

A-02. Si una entidad que es grupo BERT se baja a sus miembros para poder llegar a los genes.

A-03. Si PLANOS y CELDAS se importan de calibracion/ o se mueven a un módulo común.

