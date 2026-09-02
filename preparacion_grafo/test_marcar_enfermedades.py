"""Tests del marcado de enfermedades reales en la capa Disease.

Dos grupos. Los primeros prueban el criterio en Python sobre casos armados a mano y no necesitan
servicios. Los segundos se saltean solos si Neo4j no responde y verifican lo que de verdad
importa: que lo escrito en la base coincida nodo por nodo con el criterio, que la marca esté
puesta y que no haya tocado otros tipos de nodo. Esa comparación es la razón de que el criterio
exista dos veces, en Cypher y en Python: si las implementaciones divergen, acá se ve.
"""
import os
import sys
import unittest

#rutas armadas desde este archivo y no desde el directorio de trabajo, para que la suite corra
#igual desde acá que desde correr_tests.py en la raíz del proyecto
_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.join(_AQUI, "..", "loader"))

from neo4j import GraphDatabase

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from marcar_enfermedades_reales import PROPIEDAD, RAICES_NO_ENFERMEDAD, es_enfermedad, verificar


class TestCriterio(unittest.TestCase):
    def test_nodo_comun_es_enfermedad(self):
        self.assertTrue(es_enfermedad("MONDO_0005130", ["MONDO_0004335"], "celiac disease"))

    def test_descendiente_de_medicion_no_lo_es(self):
        self.assertFalse(
            es_enfermedad("OBA_0000061", ["EFO_0001444", "OBA_0000001"], "circulating fibrinogen"))

    def test_las_propias_raices_quedan_descartadas(self):
        """El linaje incluye al nodo mismo, asi que una raiz no sobrevive a su propio criterio."""
        for raiz in RAICES_NO_ENFERMEDAD:
            self.assertFalse(es_enfermedad(raiz, [], "una raíz"), raiz)

    def test_sin_nombre_no_sobrevive(self):
        self.assertFalse(es_enfermedad("EFO_0010269", ["MONDO_0000001"], None))
        self.assertFalse(es_enfermedad("EFO_0010269", ["MONDO_0000001"], "   "))

    def test_sin_ancestros_es_enfermedad_si_tiene_nombre(self):
        """Los nodos raiz de la taxonomia de enfermedades no traen ancestors y deben sobrevivir."""
        self.assertTrue(es_enfermedad("MONDO_0005130", None, "celiac disease"))

    def test_una_sola_raiz_alcanza_para_descartar(self):
        linaje = ["MONDO_0000001", "EFO_0002571"]
        self.assertFalse(es_enfermedad("EFO_0009090", linaje, "un procedimiento"))


def _driver():
    try:
        d = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        d.verify_connectivity()
        return d
    except Exception:
        return None


DRIVER = _driver()


@unittest.skipIf(DRIVER is None, "Neo4j no responde")
class TestMarcadoEnLaBase(unittest.TestCase):
    def test_todos_los_nodos_estan_marcados(self):
        """Sin nodos sin valor: un None significaria que el marcado nunca se corrio sobre ese nodo."""
        with DRIVER.session() as sesion:
            estado = verificar(sesion)
        self.assertNotIn(None, estado, "hay nodos Disease sin la propiedad, correr el script")
        self.assertEqual(sum(estado.values()), 36345)

    def test_coincide_con_el_criterio_en_python(self):
        """La comparacion nodo por nodo entre lo escrito por Cypher y el criterio en Python."""
        with DRIVER.session() as sesion:
            filas = list(sesion.run(
                f"MATCH (d:Disease) RETURN d.id AS id, d.name AS nombre, "
                f"d.ancestors AS ancestros, d.{PROPIEDAD} AS marca"))
        discrepantes = [f["id"] for f in filas
                        if f["marca"] != es_enfermedad(f["id"], f["ancestros"], f["nombre"])]
        self.assertEqual(discrepantes[:10], [], f"{len(discrepantes)} nodos discrepan")

    def test_no_toca_otros_tipos_de_nodo(self):
        with DRIVER.session() as sesion:
            otros = sesion.run(f"MATCH (n) WHERE n.{PROPIEDAD} IS NOT NULL AND NOT n:Disease "
                               "RETURN count(*) AS n").single()["n"]
        self.assertEqual(otros, 0)

    def test_casos_de_control(self):
        """Dos enfermedades de ontologias distintas sobreviven, dos nodos que no lo son caen."""
        esperado = {"MONDO_0005130": True,    #celiaquia
                    "EFO_0000095": True,      #leucemia linfocitica cronica, sin id MONDO
                    "OBA_0000061": False,     #niveles de fibrinogeno circulante
                    "EFO_0001444": False}     #la raiz measurement
        with DRIVER.session() as sesion:
            for identificador, valor in esperado.items():
                marca = sesion.run(f"MATCH (d:Disease {{id:$i}}) RETURN d.{PROPIEDAD} AS m",
                                   i=identificador).single()["m"]
                self.assertEqual(marca, valor, identificador)

    def test_existe_el_indice(self):
        with DRIVER.session() as sesion:
            nombres = [r["name"] for r in sesion.run(
                "SHOW INDEXES YIELD name, properties WHERE $p IN properties RETURN name",
                p=PROPIEDAD)]
        self.assertTrue(nombres, f"no hay indice sobre {PROPIEDAD}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
