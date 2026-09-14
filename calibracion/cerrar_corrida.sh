#!/bin/bash
#Cierre del batch: espera a que no quede ningun runner, borra casos a medio escribir, y corre
#iteracion0, graficos por plano, resumen, conteo, informe y verificacion. Deja todo en
#resultados/RESUMEN_corrida.txt. Adaptado de cerrar_corrida.sh de optimuskg: dos planos en vez
#de cuatro, e iteracion0 se corre aca y no en paralelo al batch (en la corrida 4 correrlo junto a
#los runners los freno al doble). iteracion0 necesita neo4j-thesis levantado.
#
#Uso: ./cerrar_corrida.sh [parcial]
cd "$(dirname "$0")" || exit 1
PY=${PY:-python}
#la carpeta y la version de los grupos BERT se toman del entorno, por defecto las del primer batch
DIR=${CRECIMIENTO_RESULTADOS:-resultados}
export CRECIMIENTO_GRUPOS_BERT=${CRECIMIENTO_GRUPOS_BERT:-excluidos}
export PYTHONHASHSEED=42
export CRECIMIENTO_RESULTADOS=$DIR
export CRECIMIENTO_N_POR_BIN=50

if [ "$1" != "parcial" ]; then
  while pgrep -f "paso2_runner[.]py --celdas" > /dev/null; do sleep 120; done
fi

{
echo "=== cierre ${1:-final} $(date)"
echo "=== limpieza de casos a medio escribir"
$PY - "$DIR" "${1:-final}" <<'PYEOF'
import os, sys
import pandas as pd
directorio = sys.argv[1]
borrados = 0
for archivo in sorted(os.listdir(os.path.join(directorio, "trazas"))):
    traza = os.path.join(directorio, "trazas", archivo)
    recall = os.path.join(directorio, "recalls", archivo)
    legible = os.path.exists(recall)
    if legible:
        try:
            pd.read_parquet(traza); pd.read_parquet(recall)
        except Exception:
            legible = False
    if not legible:
        if sys.argv[2] == "parcial":
            print(f"  {archivo}: incompleto, se saltea"); continue
        for ruta in (traza, recall):
            if os.path.exists(ruta): os.remove(ruta)
        borrados += 1
        print(f"  borrado {archivo}: a medio escribir")
print(f"  casos incompletos borrados: {borrados}")
PYEOF

echo "=== iteracion0 $(date)"
$PY paso3_iteracion0.py > "$DIR/iteracion0.log" 2>&1 && echo "  iteracion0 listo" || echo "  iteracion0 FALLO (ver $DIR/iteracion0.log)"
echo "=== graficos, tablas, informe y verificacion $(date)"
for plano in gene disease; do
  $PY -c "from graficos import grafico_plano; grafico_plano('$plano')"
done
$PY paso4_resumen.py > "$DIR/resumen.log" 2>&1 && echo "  resumen listo" || echo "  resumen FALLO (ver $DIR/resumen.log)"
$PY paso5_conteo.py > "$DIR/conteo.log" 2>&1 && echo "  conteo listo" || echo "  conteo FALLO (ver $DIR/conteo.log)"
$PY paso6_informe.py && echo "  informe listo" || echo "  informe FALLO"
$PY paso7_verificar.py > "$DIR/verificacion.log" 2>&1
echo "  verificacion: $(tail -1 "$DIR/verificacion.log")"

{
  echo "batch sobre PrimeKG integrado en $DIR: disease_a_gene y gene_a_disease, 50 por bin, presupuesto 100, grupos BERT $CRECIMIENTO_GRUPOS_BERT."
  echo "cierre ${1:-final} $(date)"
  echo
  echo "casos completos por celda (150 esperados):"
  ls "$DIR/trazas" | sed -E 's/__.*//' | sort | uniq -c | awk '{printf "  %-24s %3d\n", $2, $1}'
  echo
  echo "segundos por caso, medidos en los logs:"
  for log in "$DIR"/batch_*.log; do
    grep -o "\[[a-z_]*\] [0-9]*/[0-9]* [^ ]* ok ([0-9.]*s)" "$log" \
      | sed -E 's/\[([a-z_]*)\].*ok \(([0-9.]*)s\)/\1 \2/' \
      | awk '{s[$1]+=$2; n[$1]++} END {for (c in s) printf "  %-24s %6.1f s/caso (%d casos)\n", c, s[c]/n[c], n[c]}'
  done | sort
  echo
  echo "verificacion:"
  sed 's/^/  /' "$DIR/verificacion.log"
} > "$DIR/RESUMEN_corrida.txt"
cat "$DIR/RESUMEN_corrida.txt"
echo "=== fin $(date)"
} > "$DIR/final_corrida.log" 2>&1
