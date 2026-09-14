#!/bin/bash
#Crea el contenedor neo4j-thesis, vacio, con PrimeKG integrado como destino.
#
#Antes hace falta el daemon de Docker: sudo systemctl start docker (con TTY, pide contrasena).
#Se crea una sola vez; despues alcanza con docker start neo4j-thesis / docker stop neo4j-thesis.
#
#La memoria se fija desde la creacion, por variables de entorno, y no despues a mano como se hizo
#con neo4j-tesis: asi la receta queda en este archivo. Los valores son chicos a proposito: el
#grafo tiene 35.839 nodos y 255.026 aristas, y la maquina tiene 7,4 GB de RAM con
#earlyoom vigilando. Conviene tener un solo contenedor de Neo4j levantado a la vez.
#
#El plugin Graph Data Science se instala igual que en neo4j-tesis (la imagen lo descarga al
#primer arranque, hace falta internet): el experimento no usa sus algoritmos, pero el cliente
#graphdatascience con el que se corre Cypher lo exige al conectar.
set -e

#la contraseña sale del .env de la raiz del repositorio (PRIMEKG_NEO4J_PASSWORD), la misma que
#despues lee neo4j/config.py
ENV="$(dirname "$0")/../../../.env"
[ -f "$ENV" ] && set -a && . "$ENV" && set +a
: "${PRIMEKG_NEO4J_PASSWORD:?falta PRIMEKG_NEO4J_PASSWORD: copiar .env.example a .env y completarlo}"

docker run -d \
  --name neo4j-thesis \
  -p 7475:7474 -p 7688:7687 \
  -v neo4j-thesis-data:/data \
  -v neo4j-thesis-logs:/logs \
  -e "NEO4J_AUTH=neo4j/$PRIMEKG_NEO4J_PASSWORD" \
  -e 'NEO4J_PLUGINS=["graph-data-science"]' \
  -e NEO4J_dbms_security_procedures_unrestricted='gds.*' \
  -e NEO4J_dbms_security_procedures_allowlist='gds.*' \
  -e NEO4J_server_memory_heap_initial__size=512M \
  -e NEO4J_server_memory_heap_max__size=512M \
  -e NEO4J_server_memory_pagecache_size=256M \
  neo4j:5-community

echo "esperando a que Neo4j acepte conexiones en el puerto 7688..."
for i in $(seq 1 60); do
  if docker exec neo4j-thesis cypher-shell -u neo4j -p "$PRIMEKG_NEO4J_PASSWORD" "RETURN 1" > /dev/null 2>&1; then
    echo "neo4j-thesis listo: web en http://localhost:7475, bolt en bolt://localhost:7688"
    exit 0
  fi
  sleep 2
done
echo "Neo4j no respondio en dos minutos; ver docker logs neo4j-thesis"
exit 1
