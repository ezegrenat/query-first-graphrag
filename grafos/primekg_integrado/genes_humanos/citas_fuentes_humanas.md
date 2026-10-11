# Citas: las fuentes de PrimeKG integrado son de genes humanos

Fecha: 2026-09-17. Reúne, con comillas, (A) los pasajes de la tesis de origen de PrimeKG integrado donde presenta y cita cada fuente de datos, (B) lo que cada fuente dice de sí misma sobre la especie que cubre, y (C) lo que muestran los archivos. La comprobación numérica está en `../genes_humanos.ipynb`. Las citas en inglés son textuales de los papers, tomadas del texto completo servido por Europe PMC; las de la tesis son textuales del PDF (la tesis de origen, en PDF).

## A. Lo que dice la tesis de origen

Sección 3.3, "Bases de datos utilizadas" (página 41):

> "Como punto de partida se tomó la red bipartita DisGeNET, considerando solo los datos curados por expertos, que consisten de 84038 asociaciones de alta calidad entre 11181 enfermedades y 9703 genes."

> "Para interconectar los genes de la red, se incorporó información sobre interacciones físicas entre las proteínas que estos codifican. Esta información se extrajo de la base de datos HIPPIE, que cuenta con una lista completa, calificada y funcionalmente comentada de las interacciones proteína-proteína del ser humano [64]."

> "Además se añadió información sobre complejos de proteínas proveniente la base de datos Signor [66]."

> "Para enriquecer la conectividad de los nodos enfermedad se utilizó la base de datos PrimeKG: Precision Medicine Oriented Knowledge Graph, un grafo de conocimiento biomédico heterogéneo que integra numerosas bases de datos de alta calidad [67]."

Sección 3.4, "Integración y curado de datos" (páginas 42 y 43):

> "Todos los nodos en DisGeNET cuentan con este tipo de identificadores únicos, que permiten mapearlos a otras bases de datos y ontologías: los genes se identifican a través de su Entrez-ID [71], mientras que para las enfermedades se utiliza el código UMLS-CUI [69]."

> "Por otro lado, se utilizaron mapeos de vocabulario entre Uniprot [72] y Entrez-ID para obtener enlaces entre complejos y proteínas de la base de datos Signor. De esta manera, se integraron a la red 421 complejos de proteínas y 1885 enlaces proteína-complejo, que conectan a los complejos con las proteínas que los conforman."

Es la única mención de especie en toda la tesis: "del ser humano", dicho de HIPPIE. De DisGeNET, SIGNOR y PrimeKG no dice de qué organismo son, y en ningún paso del pipeline (`src/data/network_merging.ipynb`, `src/data/signor_entrez_map.py` del repositorio `gcnn_gdas`) hay un filtro por especie.

Las referencias que cita la tesis (sección de referencias de la tesis):

- [50] Janet Piñero et al., "DisGeNET: a comprehensive platform integrating information on human disease-associated genes and variants", Nucleic Acids Research 45.D1 (2017), D833-D839. Acceso: marzo de 2022.
- [64] Gregorio Alanis-Lobato, Miguel A. Andrade-Navarro y Martin H. Schaefer, "HIPPIE v2.0: enhancing meaningfulness and reliability of protein-protein interaction networks", Nucleic Acids Research 45.D1 (2016), D408-D414. Acceso: marzo de 2022.
- [66] Paolo Lo Surdo, Alberto Calderone, Gianni Cesareni y Livia Perfetto, "SIGNOR: A Database of Causal Relationships Between Biological Entities. A Short Guide to Searching and Browsing", Current Protocols in Bioinformatics 58 (2017). Acceso: marzo de 2022.
- [67] Payal Chandak, Kexin Huang y Marinka Zitnik, "Building a knowledge graph to enable precision medicine", Scientific Data 10.1 (2023). Acceso: junio de 2022.
- [72] The UniProt Consortium, "UniProt: the Universal Protein Knowledgebase in 2023", Nucleic Acids Research 51 (2022).

## B. Lo que cada fuente dice de sí misma

### HIPPIE (referencia [64] de PrimeKG integrado)

Alanis-Lobato, Andrade-Navarro y Schaefer, NAR 2017, doi 10.1093/nar/gkw985, PMC5210659.

> "To this end, we generated the Human Integrated Protein–Protein Interaction rEference or HIPPIE"

> "It has been maintained by a team of biologists and developers and has established itself as a one-stop resource for querying and analyzing the human interactome."

La H del nombre es "Human". En el archivo que usa PrimeKG integrado (`external/hippie_current.txt`) las 17.322 proteínas están identificadas por entry name de UniProt con sufijo `_HUMAN` y por Entrez humano.

### DisGeNET (referencia [50] de PrimeKG integrado)

Piñero et al., NAR 2017, doi 10.1093/nar/gkw943, PMC5210640. El título ya lo dice: "human disease-associated genes and variants". En el texto:

> "To address this need we have developed DisGeNET, a discovery platform that contains a comprehensive catalogue of genes and variants associated to human diseases."

> "DisGeNET covers the whole landscape of human diseases, including Mendelian, complex, environmental and rare diseases, and disease-related traits."

PrimeKG integrado usa el subconjunto curado (`external/curated_gene_disease_associations.tsv`), con `geneId` de NCBI Gene humano.

### PrimeKG (referencia [67] de PrimeKG integrado)

Chandak, Huang y Zitnik, Scientific Data 2023, doi 10.1038/s41597-023-01960-3, PMC9893183. Sobre los genes y las interacciones:

> "Entrez Gene is a resource maintained by the NCBI that contains vast amounts of gene-specific information."

> "We use the human PPI network compiled by Menche et al."

> "We retrieved gene expression data for humans from ftp://ftp.bgee.org"

No hay una frase que diga "solo genes humanos", pero todas las fuentes de genes que integra son humanas. De PrimeKG, la tesis de origen tomó la jerarquía de MONDO y los pathways de Reactome con sus proteínas (1.350 genes con `node_source = primekg_NCBI`, todos en la lista vigente de GeneID humanos de NCBI).

### SIGNOR (referencia [66] de PrimeKG integrado)

La guía que cita PrimeKG integrado (Current Protocols 2017, doi 10.1002/cpbi.28) no es de acceso abierto. Los datos que descargó en marzo de 2022 corresponden a la versión 3.0, descrita en Lo Surdo et al., NAR 2023, doi 10.1093/nar/gkac883, PMC9825604:

> "It is important to stress that all the interactions annotated by SIGNOR curators are mapped to the human proteome and displayed as a single network that describes an abstract cell where all the proteins are expressed and active."

> "Approximately 33% of the human proteome (6750 proteins) is now integrated in the SIGNOR network."

Y sobre qué significa el organismo de una relación (es el sistema experimental, no la proteína):

> "a series of drop-down menus permit to filter the results and show only relations that are annotated with metadata related to (i) the experimental system used to demonstrate the interaction (Organism, cell type, tissue etc.)"

El mismo paper cita como parte de su contenido la red de perturbaciones celulares por infección de SARS-CoV-2 ("A resource for the network representation of cell perturbations caused by SARS-CoV-2 infection", referencia del paper). Por eso SIGNOR contiene proteínas virales que actúan sobre el proteoma humano: "mapeado al proteoma humano" no es lo mismo que "solo proteínas humanas".

## C. Lo que muestran los archivos

Medido en `../genes_humanos.ipynb` contra `Homo_sapiens.gene_info` de NCBI (16 de septiembre de 2026) y E-utilities:

| grupo | genes |
|---|---|
| humano, GeneID vigente | 17.271 |
| humano, GeneID reemplazado por otro después de 2022 | 36 |
| humano, GeneID dado de baja después de 2022 | 13 |
| viral: Spike de SARS-CoV (1489668) y de SARS-CoV-2 (43740568) | 2 |

Los 49 humanos con id viejo están tal cual en los archivos crudos de HIPPIE (42) y DisGeNET (7). Los 2 virales entran por tres filas `form complex` de SIGNOR (complejos `SIGNOR-C240`, `SIGNOR-C254`, `SIGNOR-C267`: Spike con ACE2 y con NRP1), cuyo `TAX_ID` es 9534 (Chlorocebus, células Vero) o 9606, es decir el organismo del experimento.

## D. Frase para la tesis

Los genes del grafo son humanos por construcción de sus fuentes: DisGeNET cataloga genes asociados a enfermedades humanas, HIPPIE es el interactoma humano, PrimeKG integra Entrez Gene y la red PPI humana, y SIGNOR está mapeado al proteoma humano. Las dos únicas excepciones son las proteínas Spike de SARS-CoV y SARS-CoV-2, componentes de tres complejos de SIGNOR que registran la interacción del virus con ACE2 y NRP1.
