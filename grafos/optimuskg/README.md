# OptimusKG

El grafo con el que arrancó el trabajo, evaluado y dejado el 2026-09-08. Se dejó porque el plano homogéneo de drogas no tiene con qué trabajar (`PARENT` es taxonomía, no interacción, y `SYNERGISTIC_INTERACTION` no mostró señal), y porque la capa de enfermedades necesitaba dos limpiezas previas (separar enfermedades de rasgos, deduplicar identidades) que en el grafo que lo reemplaza ya vienen resueltas. El detalle está en la bitácora.

Queda acá como registro de lo que se hizo sobre él:

- `loader/`: la carga de OptimusKG a Neo4j. Descarga los parquet publicados en Dataverse y los inserta por lotes.
- `preparacion_grafo/`: la separación de las enfermedades reales del resto de la capa `Disease` (`marcar_enfermedades_reales.py`, criterio en `limpieza_capa_disease.ipynb`), la deduplicación de identidades entre vocabularios (`redundancia.py`, `marcar_id_canonico.py`, medido en `redundancia_entre_nodos.ipynb`) y el chequeo de dónde sale el `evidence_score` (`procedencia_evidence_score.ipynb`).

Los scripts esperan el `.env` de la raíz del repositorio y un Neo4j con OptimusKG cargado.
