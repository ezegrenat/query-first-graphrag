"""Tests de las señales de redundancia entre nodos. Ninguno necesita servicios: las funciones de redundancia.py son puras y se prueban sobre casos armados a mano, varios de ellos tomados de pares reales medidos contra la base para que el test falle si alguna normalizacion deja de reconocerlos."""
import os
import sys
import unittest

import pandas as pd

#rutas armadas desde este archivo y no desde el directorio de trabajo, para que la suite corra
#igual desde aca que desde la raiz del repositorio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redundancia import (elegir_representante, es_cascara, grupos_de_equivalencia, grupos_por_clave,
                         hash_vecindario, jaccard, normalizar, normalizar_identificador,
                         pares_de_grupos, pares_desde_sssom, pares_por_referencia, pares_por_sinonimo,
                         unir_declarados, unir_senales)


class TestNormalizacion(unittest.TestCase):
    def test_apostrofe_y_mayusculas(self):
        """El par que motivo la normalizacion fuerte: las dos ontologias escriben distinto el posesivo."""
        self.assertEqual(normalizar("Hodgkin's lymphoma"), normalizar("hodgkins lymphoma"))

    def test_sufijo_intercambiable_al_final(self):
        self.assertEqual(normalizar("metabolic disease"), normalizar("metabolic disorder"))

    def test_el_sufijo_no_se_saca_del_medio(self):
        """disease adentro del nombre distingue, solo al final es intercambiable."""
        self.assertNotEqual(normalizar("disease of liver"), normalizar("of liver"))

    def test_un_nombre_de_una_sola_palabra_no_pierde_el_sufijo(self):
        """Si se sacara, disease y disorder quedarian en cadena vacia y agruparian cualquier cosa."""
        self.assertEqual(normalizar("disease"), "disease")

    def test_tildes_y_puntuacion(self):
        """Los nombres del grafo estan en ingles pero varios traen diacriticos del apellido de quien describio la enfermedad."""
        self.assertEqual(normalizar("Sjögren-Larsson  Syndrome"), "sjogren larsson")
        self.assertEqual(normalizar("Behçet's disease"), normalizar("Behcets Disease"))

    def test_limitacion_conocida_el_posesivo_deja_la_s(self):
        """Sacar el apostrofe no saca la s que lo acompaña, asi que Behcet disease y Behcet's disease no caen en la misma clave. No se corrige recortando la s final porque eso uniria plurales que si distinguen, y esos pares los levantan igual las señales estructurales."""
        self.assertNotEqual(normalizar("Behçet's disease"), normalizar("Behcet disease"))

    def test_nulo_da_cadena_vacia(self):
        self.assertEqual(normalizar(None), "")
        self.assertEqual(normalizar("   "), "")

    def test_identificador_con_los_dos_separadores(self):
        self.assertEqual(normalizar_identificador("MONDO:0007256"),
                         normalizar_identificador("MONDO_0007256"))


class TestAgrupamiento(unittest.TestCase):
    def test_grupos_ignora_nulos_y_no_los_agrupa_entre_si(self):
        """Dos nodos sin nombre no son el mismo nodo, y collect() de Cypher los juntaria."""
        filas = [{"id": "A", "name": None}, {"id": "B", "name": None}, {"id": "C", "name": "x"}]
        self.assertEqual(grupos_por_clave(filas, "name"), {})

    def test_grupos_con_normalizador(self):
        filas = [{"id": "EFO_1", "name": "Hodgkin's lymphoma"},
                 {"id": "MONDO_1", "name": "hodgkins lymphoma"},
                 {"id": "EFO_2", "name": "asthma"}]
        grupos = grupos_por_clave(filas, "name", normalizador=normalizar)
        self.assertEqual(grupos, {"hodgkins lymphoma": ["EFO_1", "MONDO_1"]})

    def test_pares_de_grupos_ordena_y_no_duplica_espejados(self):
        pares = pares_de_grupos({"x": ["MONDO_1", "EFO_1", "DOID_1"]})
        self.assertEqual([(a, b) for a, b, _ in pares],
                         [("DOID_1", "EFO_1"), ("DOID_1", "MONDO_1"), ("EFO_1", "MONDO_1")])


class TestSenales(unittest.TestCase):
    def test_sinonimo_de_uno_igual_al_nombre_de_otro(self):
        nombres = {"EFO_1": "atopic eczema", "MONDO_1": "atopic dermatitis"}
        sinonimos = {"EFO_1": ["atopic dermatitis", "eczema"]}
        self.assertEqual(pares_por_sinonimo(nombres, sinonimos),
                         [("EFO_1", "MONDO_1", "atopic dermatitis")])

    def test_sinonimo_propio_no_se_empareja_consigo_mismo(self):
        nombres = {"EFO_1": "asthma"}
        self.assertEqual(pares_por_sinonimo(nombres, {"EFO_1": ["asthma"]}), [])

    def test_referencia_cruzada_con_separador_distinto(self):
        """El caso real: el xref esta escrito con : y el nodo existe con _."""
        pares = pares_por_referencia({"EFO_0000182": ["MONDO:0007256", "UMLS:C2239176"]},
                                     ["EFO_0000182", "MONDO_0007256"])
        self.assertEqual(pares, [("EFO_0000182", "MONDO_0007256", "MONDO:0007256")])

    def test_referencia_a_un_id_que_no_esta_en_la_capa_se_descarta(self):
        self.assertEqual(pares_por_referencia({"A": ["MESH:D016604"]}, ["A", "B"]), [])

    def test_hash_de_vecindario_no_depende_del_orden_ni_de_repetidos(self):
        self.assertEqual(hash_vecindario(["PARENT:X", "TARGET:Y", "PARENT:X"]),
                         hash_vecindario(["TARGET:Y", "PARENT:X"]))

    def test_un_vecino_de_mas_cambia_el_hash(self):
        self.assertNotEqual(hash_vecindario(["PARENT:X"]), hash_vecindario(["PARENT:X", "PARENT:Z"]))

    def test_vecindario_vacio(self):
        self.assertEqual(hash_vecindario([]), "")

    def test_jaccard_a_mano(self):
        """Tres vecinos compartidos sobre cinco distintos."""
        self.assertAlmostEqual(jaccard(["a", "b", "c", "d"], ["a", "b", "c", "e"]), 3 / 5)
        self.assertEqual(jaccard(["a"], ["a"]), 1.0)
        self.assertEqual(jaccard([], []), 0.0)

    def test_cascara(self):
        """El perfil de los gemelos MONDO de CTD: sin jerarquia y con un solo tipo de relacion."""
        self.assertTrue(es_cascara(0, ["LINKED_TO", "LINKED_TO"]))
        self.assertFalse(es_cascara(3, ["LINKED_TO"]))
        self.assertFalse(es_cascara(0, ["LINKED_TO", "ASSOCIATED_WITH"]))


class TestEquivalenciasDeclaradas(unittest.TestCase):
    """Las tres piezas que construyen la tabla de equivalencias a partir de lo que declara la ontologia, probadas sobre un SSSOM de juguete con la forma exacta del archivo real."""

    #seis filas con los casos que importan: separador distinto, predicado que no entra, objeto que no
    #existe en la capa, y el mismo par escrito dos veces en distinto orden
    SSSOM = pd.DataFrame([
        {"subject_id": "MONDO:0007256", "predicate_id": "skos:exactMatch", "object_id": "EFO:0000182"},
        {"subject_id": "MONDO:0004980", "predicate_id": "skos:exactMatch", "object_id": "EFO:0000274"},
        {"subject_id": "MONDO:0007120", "predicate_id": "skos:exactMatch", "object_id": "Orphanet:1069"},
        {"subject_id": "MONDO:0007120", "predicate_id": "skos:broadMatch", "object_id": "EFO:0000274"},
        {"subject_id": "MONDO:0007256", "predicate_id": "skos:exactMatch", "object_id": "UMLS:C2239176"},
        {"subject_id": "EFO:0000182", "predicate_id": "skos:exactMatch", "object_id": "MONDO:0007256"},
    ])
    CAPA = ["MONDO_0007256", "EFO_0000182", "MONDO_0004980", "EFO_0000274",
            "MONDO_0007120", "Orphanet_1069"]

    def test_sssom_solo_pares_con_los_dos_extremos_en_la_capa(self):
        """UMLS:C2239176 no es un nodo del grafo, asi que ese mapeo no es un duplicado."""
        pares = pares_desde_sssom(self.SSSOM, self.CAPA)
        self.assertEqual(pares, [("EFO_0000182", "MONDO_0007256"),
                                 ("EFO_0000274", "MONDO_0004980"),
                                 ("MONDO_0007120", "Orphanet_1069")])

    def test_sssom_respeta_el_predicado(self):
        """El broadMatch entre MONDO_0007120 y EFO_0000274 no entra con el predicado por defecto, y si al pedirlo."""
        self.assertNotIn(("EFO_0000274", "MONDO_0007120"), pares_desde_sssom(self.SSSOM, self.CAPA))
        self.assertEqual(pares_desde_sssom(self.SSSOM, self.CAPA, predicado="skos:broadMatch"),
                         [("EFO_0000274", "MONDO_0007120")])

    def test_sssom_no_devuelve_espejados(self):
        """El par MONDO_0007256 / EFO_0000182 esta escrito en las dos direcciones y sale una sola vez."""
        pares = pares_desde_sssom(self.SSSOM, self.CAPA)
        self.assertEqual(sum(1 for a, b in pares if {a, b} == {"MONDO_0007256", "EFO_0000182"}), 1)

    def test_unir_declarados_marca_ambas(self):
        tabla = unir_declarados({"xrefs": [("A", "B"), ("C", "D")], "sssom": [("B", "A"), ("E", "F")]})
        self.assertEqual(dict(zip(zip(tabla.id_a, tabla.id_b), tabla.fuente)),
                         {("A", "B"): "ambas", ("C", "D"): "xrefs", ("E", "F"): "sssom"})

    def test_unir_declarados_vacio(self):
        tabla = unir_declarados({"xrefs": [], "sssom": []})
        self.assertEqual(len(tabla), 0)
        self.assertEqual(list(tabla.columns), ["id_a", "id_b", "fuente"])

    def test_grupos_transitivos(self):
        """A igual a B y B igual a C es un solo grupo de tres, mas un par suelto aparte."""
        self.assertEqual(grupos_de_equivalencia([("A", "B"), ("B", "C"), ("X", "Y")]),
                         [["A", "B", "C"], ["X", "Y"]])

    def test_grupos_no_dependen_del_orden(self):
        self.assertEqual(grupos_de_equivalencia([("B", "C"), ("X", "Y"), ("A", "B")]),
                         grupos_de_equivalencia([("A", "B"), ("B", "C"), ("X", "Y")]))

    def test_grupos_sin_pares(self):
        self.assertEqual(grupos_de_equivalencia([]), [])


class TestRepresentante(unittest.TestCase):
    """La cascada se prueba nivel por nivel, cada uno con los anteriores empatados a proposito."""

    def test_gana_el_de_mas_aristas(self):
        elegido = elegir_representante(["EFO_1", "MONDO_1"],
                                       grado={"EFO_1": 13889, "MONDO_1": 2}, jerarquia={})
        self.assertEqual(elegido, "EFO_1")

    def test_empatado_el_grado_gana_el_que_tiene_jerarquia(self):
        """El patron real de los empates medidos: MONDO con jerarquia contra Orphanet sin ella."""
        elegido = elegir_representante(["MONDO_0009182", "Orphanet_79404"],
                                       grado={"MONDO_0009182": 70, "Orphanet_79404": 70},
                                       jerarquia={"MONDO_0009182": 1, "Orphanet_79404": 0})
        self.assertEqual(elegido, "MONDO_0009182")

    def test_empatado_todo_gana_la_ontologia_de_mayor_prioridad(self):
        grado = {"EFO_1": 10, "MONDO_1": 10}
        jerarquia = {"EFO_1": 1, "MONDO_1": 1}
        self.assertEqual(elegir_representante(["EFO_1", "MONDO_1"], grado, jerarquia), "MONDO_1")

    def test_ultimo_desempate_por_identificador(self):
        """Nunca se llego a este nivel sobre los datos reales, existe para que el resultado no dependa del orden de entrada."""
        grado = {"MONDO_2": 5, "MONDO_1": 5}
        jerarquia = {"MONDO_2": 0, "MONDO_1": 0}
        self.assertEqual(elegir_representante(["MONDO_2", "MONDO_1"], grado, jerarquia), "MONDO_1")

    def test_no_depende_del_orden_del_grupo(self):
        grado, jerarquia = {"A_1": 5, "B_1": 5}, {"A_1": 0, "B_1": 0}
        self.assertEqual(elegir_representante(["A_1", "B_1"], grado, jerarquia),
                         elegir_representante(["B_1", "A_1"], grado, jerarquia))

    def test_un_nodo_sin_grado_registrado_no_rompe(self):
        self.assertEqual(elegir_representante(["A_1", "B_1"], {"A_1": 3}, {}), "A_1")


class TestUnionDeSenales(unittest.TestCase):
    def test_un_par_en_dos_senales_sale_una_sola_vez(self):
        tabla = unir_senales({"nombre": [("EFO_1", "MONDO_1", "hodgkins lymphoma")],
                              "xref": [("MONDO_1", "EFO_1", "MONDO:1")]})
        self.assertEqual(len(tabla), 1)
        fila = tabla.iloc[0]
        self.assertEqual((fila["id_a"], fila["id_b"]), ("EFO_1", "MONDO_1"))
        self.assertTrue(fila["nombre"] and fila["xref"])
        self.assertEqual(fila["n_senales"], 2)

    def test_par_en_una_sola_senal_deja_la_otra_en_falso(self):
        tabla = unir_senales({"nombre": [("A", "B", "x")], "xref": []})
        self.assertEqual(list(tabla["n_senales"]), [1])
        self.assertFalse(tabla.iloc[0]["xref"])
        self.assertIsNone(tabla.iloc[0]["detalle_xref"])

    def test_ordena_por_cantidad_de_senales(self):
        tabla = unir_senales({"nombre": [("A", "B", "x"), ("C", "D", "y")],
                              "xref": [("C", "D", "z")]})
        self.assertEqual(list(tabla["id_a"]), ["C", "A"])

    def test_sin_pares_devuelve_tabla_vacia_con_las_columnas(self):
        tabla = unir_senales({"nombre": [], "xref": []})
        self.assertEqual(len(tabla), 0)
        for columna in ("id_a", "id_b", "nombre", "xref", "n_senales"):
            self.assertIn(columna, tabla.columns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
