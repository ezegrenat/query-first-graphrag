# PrimeKG integrado

El grafo sobre el que sigue el trabajo desde el 2026-09-08. Lo armó el laboratorio de Ariel Chernomoretz sobre PrimeKG: toma de ahí la capa de enfermedades y completa el resto con fuentes curadas. Cada capa viene de una fuente distinta:

| capa | fuente | quién la armó |
|---|---|---|
| enfermedades (ontología MONDO, descripciones, grupos BERT) | PrimeKG (Chandak, Huang y Zitnik, 2023) | integración de Ingrid Heuer, tesis `gcnn_gdas` (2023) |
| gen-enfermedad | DisGeNET, asociaciones curadas | ídem |
| interactoma (gen-gen) | HIPPIE con confianza mayor a 0,73, más SIGNOR y sus complejos | ídem |
| pathways | Reactome | ídem |
| drogas: indicaciones y dianas | PrimeKG nativo (DrugBank) | este trabajo |
| drogas: similaridad química | capa propia del laboratorio, en preparación | Gonzalo (laboratorio) |

En números: 35.839 nodos (17.743 genes, 16.079 enfermedades, 2.017 pathways) y 255.026 aristas. Las enfermedades están identificadas por CUI de UMLS y los genes por Entrez; el puente a los MONDO de PrimeKG es `processed/disease_mappings.csv`. Dos limpiezas que en OptimusKG hubo que hacer a mano acá ya vienen resueltas: la identidad entre vocabularios de enfermedades y la poda de hubs sin evidencia molecular.

## Qué hay

- `datos/`: los CSV, que no se versionan (750 MB) y se piden al laboratorio. `external/` trae las fuentes crudas, incluido PrimeKG nativo completo (`primekg_nodes.csv`, `primekg_edges.csv`), y `processed/` el grafo integrado (`merged_nodes.csv`, `merged_edges.csv`, `disease_bert_edges.csv`, `disease_mappings.csv`). Puede ser un enlace simbólico a donde estén.
- `neo4j/`: la carga del grafo al contenedor `neo4j-thesis`. `crear_contenedor.sh` lo crea, `cargar_grafo.py` inserta nodos y aristas (una sola vez cada arista, aunque el CSV las guarda en los dos sentidos) y `verificar_carga.py` compara conteo por conteo lo cargado contra los CSV.
- `datos_primekg.py`: el único módulo que lee PrimeKG nativo. Define las capas bipartitas y los planos homogéneos entre genes, enfermedades y fenotipos, y lista los pares droga-enfermedad de `indication`.
- `capas_y_planos.ipynb`: la caracterización de PrimeKG nativo (grados por capa, componentes y hubs por plano), ejecutado.
- `grupos_bert.ipynb`: cómo están armados los 1.040 grupos BERT en el grafo integrado y qué cuesta excluirlos del plano de enfermedades. Es la medición detrás de la decisión de dejarlos fuera del análisis.

## Cómo se carga

Con Docker andando y el `.env` de la raíz completo (claves `PRIMEKG_NEO4J_*`):

```bash
grafos/primekg_integrado/neo4j/crear_contenedor.sh     # una sola vez
python grafos/primekg_integrado/neo4j/cargar_grafo.py
python grafos/primekg_integrado/neo4j/verificar_carga.py
```

Después alcanza con `docker start neo4j-thesis`. La carga es idempotente.
