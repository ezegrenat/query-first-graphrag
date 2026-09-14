#!/bin/bash
#mantiene la maquina despierta mientras queden runners del batch.
#
#No cambia ninguna configuracion: toma un inhibidor de logind que vive lo que vive este proceso
#y desaparece solo cuando el batch termina. Si la maquina se suspende en medio de una corrida,
#los procesos se congelan y siguen al despertar (no se corrompe nada, el computo es
#determinista), pero el batch queda parado esas horas.
exec systemd-inhibit --what=sleep:idle:handle-lid-switch \
     --who="batch calibracion" --why="experimento de proyecciones sobre PrimeKG integrado" \
     bash -c 'while pgrep -f "runner[.]py --celdas" > /dev/null; do sleep 60; done'
