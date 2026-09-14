#!/bin/bash
#Version con los grupos BERT en el plano de enfermedades (2026-09-11), comparada contra el primer
#batch, que los excluye. Lo que cambia y lo que no:
#- disease_a_gene corre en el plano gene, que no toca a los grupos, y sus anclas son enfermedades
#  con genes, que los grupos nunca son. Es identica en las dos versiones: se copia de resultados/.
#- gene_a_disease se vuelve a correr con las mismas 150 anclas (comparacion pareada: la misma
#  consulta sobre dos redes). Cada gen puede ganar semillas, porque sus enfermedades miembro de un
#  grupo vuelven al plano, pero conserva el bin del primer batch para comparar ancla contra ancla.
#- paso0 se corre igual, para tener las distribuciones y el sorteo que le tocaria a esta version;
#  ese sorteo se guarda como casos_sorteo_propio.csv y no se usa.
#- los controles no sortean grupos como semilla (celdas.nodos_que_no_pueden_ser_semilla).
#
#Uso: nohup ./correr_con_grupos.sh > resultados_con_grupos_lanzamiento.log 2>&1 &
cd "$(dirname "$0")" || exit 1
PY=${PY:-python}
BASE=resultados
DIR=resultados_con_grupos
export PYTHONHASHSEED=42
export CRECIMIENTO_RESULTADOS=$DIR
export CRECIMIENTO_GRUPOS_BERT=incluidos
export CRECIMIENTO_N_POR_BIN=50

echo "=== inicio $(date): grupos BERT incluidos, carpeta $DIR"
mkdir -p "$DIR/trazas" "$DIR/recalls"
$PY paso0.py > "$DIR/paso0.log" 2>&1 || { echo "paso0 FALLO"; cat "$DIR/paso0.log"; exit 1; }
mv "$DIR/casos.csv" "$DIR/casos_sorteo_propio.csv"
cp "$BASE/casos.csv" "$DIR/casos.csv"
cp "$BASE"/trazas/disease_a_gene__* "$DIR/trazas/"
cp "$BASE"/recalls/disease_a_gene__* "$DIR/recalls/"
tail -3 "$DIR/paso0.log"

echo "=== runner gene_a_disease $(date)"
$PY runner.py --celdas gene_a_disease > "$DIR/batch_gene_a_disease.log" 2>&1 || { echo "runner FALLO"; tail "$DIR/batch_gene_a_disease.log"; exit 1; }
tail -1 "$DIR/batch_gene_a_disease.log"

echo "=== cierre $(date)"
./cerrar_corrida.sh
tail -25 "$DIR/final_corrida.log"
