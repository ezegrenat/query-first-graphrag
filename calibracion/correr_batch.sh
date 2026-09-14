#!/bin/bash
#Batch del experimento sobre PrimeKG integrado (2026-09-10): las dos celdas cruzadas, 50 anclas
#por bin, presupuesto 100, sin hora de corte. Un proceso por celda, que aca es lo mismo que un
#proceso por plano: disease_a_gene corre en el interactoma y se lleva casi todo el computo
#(unas dos horas segun paso1_smoke.py), gene_a_disease corre en el plano de MONDO y tarda minutos.
#
#Los runners leen de Neo4j solo al arrancar (los vecinos de la capa B de cada ancla); despues
#trabajan sobre el cache del plano. Es reanudable: un caso con sus dos parquet se saltea, asi que
#si earlyoom mata un runner alcanza con volver a lanzar esto.
#
#Uso: nohup ./correr_batch.sh > resultados/lanzamiento.log 2>&1 &
cd "$(dirname "$0")" || exit 1
PY=${PY:-python}
DIR=resultados
export PYTHONHASHSEED=42
export CRECIMIENTO_RESULTADOS=$DIR
export CRECIMIENTO_N_POR_BIN=50

[ -e "$DIR/casos.csv" ] || { echo "falta $DIR/casos.csv: correr paso0_sorteo.py antes"; exit 1; }
echo "=== inicio $(date): 2 celdas, 50 por bin, presupuesto 100, sin corte"
$PY paso2_runner.py --celdas disease_a_gene > "$DIR/batch_disease_a_gene.log" 2>&1 &
$PY paso2_runner.py --celdas gene_a_disease > "$DIR/batch_gene_a_disease.log" 2>&1 &
sleep 5
./inhibir_suspension.sh > "$DIR/inhibidor.log" 2>&1 &
sleep 20
echo "procesos activos:"
ps -eo args | grep "^$PY paso2_runner.py" | sed 's/.*--celdas/  celdas:/'
free -m | awk '/^Mem/{print "RAM disponible con los runners arriba:", $7"MB"}'
