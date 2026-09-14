"""Tests del marcado de canonical_id en la capa Disease. Tres grupos. Los primeros prueban la construccion y validacion del mapeo sobre pares armados a mano y no necesitan servicios. El segundo contrasta las piezas del criterio que el script tiene escritas adentro contra las de redundancia.py, que es la copia que usa el notebook, para que una divergencia entre las dos se vea. Los segundos recalculan el mapeo contra la base con las mismas funciones del script y lo comparan nodo por nodo con lo escrito, y se saltean solos si Neo4j no responde o si el marcado todavia no se corrio, que es el estado esperado hasta que Ezequiel decida aplicarlo."""
import os
import sys
import unittest

import pandas as pd

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.join(_AQUI, "..", "loader"))

from neo4j import GraphDatabase

import marcar_id_canonico as canonico

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from marcar_id_canonico import (MONDO_SSSOM_SHA256, PROPIEDAD, RUTA_SSSOM, calcular, construir_mapeo,
                                validar_mapeo, verificar)

#el script no importa redundancia.py a proposito. este test si lo hace, para comparar las dos
#copias, y se saltea si el modulo no esta en vez de romper los demas tests
try:
    import redundancia
except ImportError:
    redundancia = None


class TestConstruccionDelMapeo(unittest.TestCase):
    def test_par_simple_gana_el_de_mas_aristas(self):
        """El testigo del issue 204: el EFO con 3.215 aristas absorbe al MONDO con 12."""
        mapeo = construir_mapeo({("EFO_0000274", "MONDO_0004980")},
                                grado={"EFO_0000274": 3215, "MONDO_0004980": 12}, jerarquia={})
        self.assertEqual(mapeo, {"EFO_0000274": "EFO_0000274", "MONDO_0004980": "EFO_0000274"})

    def test_transitividad(self):
        """A igual a B y B igual a C forman un solo grupo con un solo representante."""
        mapeo = construir_mapeo({("A_1", "B_1"), ("B_1", "C_1")},
                                grado={"A_1": 5, "B_1": 50, "C_1": 7}, jerarquia={})
        self.assertEqual(set(mapeo.values()), {"B_1"})
        self.assertEqual(set(mapeo), {"A_1", "B_1", "C_1"})

    def test_el_orden_de_los_pares_no_cambia_el_resultado(self):
        grado = {"A_1": 1, "B_1": 1, "C_1": 1}
        jerarquia = {"A_1": 0, "B_1": 0, "C_1": 0}
        self.assertEqual(construir_mapeo({("A_1", "B_1"), ("B_1", "C_1")}, grado, jerarquia),
                         construir_mapeo({("B_1", "C_1"), ("A_1", "B_1")}, grado, jerarquia))

    def test_sin_pares_el_mapeo_es_vacio(self):
        self.assertEqual(construir_mapeo(set(), {}, {}), {})

    def test_validar_rechaza_cadenas(self):
        """Una cadena A a B a C dejaria a B con canonical_id distinto de id sin ser duplicado de nadie."""
        with self.assertRaises(ValueError):
            validar_mapeo({"A": "B", "B": "C", "C": "C"})

    def test_validar_rechaza_representante_ausente(self):
        with self.assertRaises(ValueError):
            validar_mapeo({"A": "B"})

    def test_validar_acepta_un_mapeo_bien_formado(self):
        validar_mapeo({"A": "A", "B": "A", "C": "C"})


@unittest.skipIf(redundancia is None, "redundancia.py no esta en la carpeta")
class TestLasDosCopiasCoinciden(unittest.TestCase):
    """El criterio esta escrito dos veces, adentro del script y en redundancia.py para el notebook. Estos tests las corren sobre las mismas entradas y comparan, que es la unica forma de que una divergencia aparezca antes de que las dos versiones cuenten cosas distintas."""

    def test_normalizar_identificador(self):
        for entrada in ["MONDO:0007256", "MONDO_0007256", "  EFO:0000274 ", "", None, 42]:
            self.assertEqual(canonico.normalizar_identificador(entrada),
                             redundancia.normalizar_identificador(entrada), entrada)

    def test_pares_por_referencia(self):
        referencias = {"MONDO_0004980": ["EFO:0000274", "DOID:3310"],
                       "EFO_0000274": None,
                       "MONDO_0000001": ["NCIT:C2991"]}
        existentes = ["MONDO_0004980", "EFO_0000274", "MONDO_0000001"]
        self.assertEqual(canonico.pares_por_referencia(referencias, existentes),
                         redundancia.pares_por_referencia(referencias, existentes))

    def test_pares_desde_sssom(self):
        mapeos = pd.DataFrame({
            "subject_id": ["MONDO:0004980", "MONDO:0004980", "MONDO:0000001", "MONDO:0007256"],
            "predicate_id": ["skos:exactMatch", "skos:broadMatch", "skos:exactMatch", "skos:exactMatch"],
            "object_id": ["EFO:0000274", "ICD10CM:L20", "DOID:4", "Orphanet:9999"]})
        existentes = ["MONDO_0004980", "EFO_0000274", "MONDO_0000001", "MONDO_0007256"]
        self.assertEqual(canonico.pares_desde_sssom(mapeos, existentes),
                         redundancia.pares_desde_sssom(mapeos, existentes))

    def test_grupos_de_equivalencia(self):
        #la cadena y el nodo compartido son los dos casos que obligan a unir grupos
        pares = [("A_1", "B_1"), ("B_1", "C_1"), ("D_1", "E_1"), ("F_1", "E_1")]
        self.assertEqual(canonico.grupos_de_equivalencia(pares),
                         redundancia.grupos_de_equivalencia(pares))

    def test_elegir_representante_en_los_cuatro_niveles(self):
        casos = [
            #gana por grado
            (["MONDO_1", "Orphanet_1"], {"MONDO_1": 5, "Orphanet_1": 90}, {}),
            #empata el grado y decide la jerarquia
            (["MONDO_1", "Orphanet_1"], {"MONDO_1": 9, "Orphanet_1": 9},
             {"MONDO_1": 0, "Orphanet_1": 3}),
            #empatan las dos y decide la ontologia
            (["MONDO_1", "Orphanet_1", "EFO_1"], {}, {}),
            #mismo espacio en todo el grupo, decide el identificador
            (["MONDO_9", "MONDO_2"], {}, {}),
        ]
        for grupo, grado, jerarquia in casos:
            self.assertEqual(canonico.elegir_representante(grupo, grado, jerarquia),
                             redundancia.elegir_representante(grupo, grado, jerarquia), grupo)

    def test_la_prioridad_de_ontologia_es_la_misma(self):
        self.assertEqual(canonico.PRIORIDAD_DE_ONTOLOGIA, redundancia.PRIORIDAD_DE_ONTOLOGIA)


def _driver():
    try:
        d = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        d.verify_connectivity()
        return d
    except Exception:
        return None


DRIVER = _driver()


def _marcado_aplicado():
    if DRIVER is None:
        return False
    with DRIVER.session() as sesion:
        return verificar(sesion)["sin marcar"] < 36345


@unittest.skipIf(DRIVER is None, "Neo4j no responde")
@unittest.skipIf(DRIVER is not None and not _marcado_aplicado(), "el marcado no se corrio todavia")
class TestMarcadoEnLaBase(unittest.TestCase):
    def test_todos_los_nodos_estan_marcados(self):
        """Sin nodos sin valor: un None significaria que el marcado nunca se corrio sobre ese nodo."""
        with DRIVER.session() as sesion:
            estado = verificar(sesion)
        self.assertEqual(estado["sin marcar"], 0)
        self.assertEqual(estado["canonicos"] + estado["absorbidos"], 36345)

    def test_coincide_con_el_mapeo_recalculado_nodo_por_nodo(self):
        """Se recalcula el mapeo con las mismas fuentes declaradas y se compara con lo escrito, incluidos los nodos que no estan en el mapeo y tienen que apuntarse a si mismos."""
        with DRIVER.session() as sesion:
            mapeo, _ = calcular(sesion)
            filas = list(sesion.run(f"MATCH (d:Disease) RETURN d.id AS id, d.{PROPIEDAD} AS canonico"))
        discrepantes = [f["id"] for f in filas if f["canonico"] != mapeo.get(f["id"], f["id"])]
        self.assertEqual(discrepantes[:10], [], f"{len(discrepantes)} nodos discrepan")

    def test_todo_canonico_es_enfermedad_real(self):
        """Un absorbido nunca puede apuntar a un nodo que la limpieza anterior descarto."""
        with DRIVER.session() as sesion:
            malos = sesion.run(f"""
                MATCH (d:Disease) WHERE d.{PROPIEDAD} <> d.id
                MATCH (c:Disease {{id: d.{PROPIEDAD}}}) WHERE NOT c.is_truly_disease
                RETURN count(*) AS n""").single()["n"]
        self.assertEqual(malos, 0)

    def test_ningun_absorbido_es_a_su_vez_representante(self):
        """En la base no puede haber cadenas: el canonico de todo absorbido se apunta a si mismo."""
        with DRIVER.session() as sesion:
            cadenas = sesion.run(f"""
                MATCH (d:Disease) WHERE d.{PROPIEDAD} <> d.id
                MATCH (c:Disease {{id: d.{PROPIEDAD}}}) WHERE c.{PROPIEDAD} <> c.id
                RETURN count(*) AS n""").single()["n"]
        self.assertEqual(cadenas, 0)

    def test_no_toca_otros_tipos_de_nodo(self):
        with DRIVER.session() as sesion:
            otros = sesion.run(f"MATCH (n) WHERE n.{PROPIEDAD} IS NOT NULL AND NOT n:Disease "
                               "RETURN count(*) AS n").single()["n"]
        self.assertEqual(otros, 0)

    def test_caso_testigo_del_issue_204(self):
        with DRIVER.session() as sesion:
            canonico = sesion.run(f"MATCH (d:Disease {{id: 'MONDO_0004980'}}) RETURN d.{PROPIEDAD} AS c").single()["c"]
        self.assertEqual(canonico, "EFO_0000274")

    def test_existe_el_indice(self):
        with DRIVER.session() as sesion:
            nombres = [r["name"] for r in sesion.run(
                "SHOW INDEXES YIELD name, properties WHERE $p IN properties RETURN name", p=PROPIEDAD)]
        self.assertTrue(nombres, f"no hay indice sobre {PROPIEDAD}")


@unittest.skipIf(not os.path.exists(RUTA_SSSOM), "el archivo SSSOM no esta bajado")
class TestArchivoSSSOM(unittest.TestCase):
    def test_el_archivo_en_disco_es_el_del_release(self):
        import hashlib
        with open(RUTA_SSSOM, "rb") as archivo:
            self.assertEqual(hashlib.sha256(archivo.read()).hexdigest(), MONDO_SSSOM_SHA256)


if __name__ == "__main__":
    unittest.main(verbosity=2)
