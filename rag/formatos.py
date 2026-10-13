"""lo que la busqueda pone en el prompt como "Target response length and format". prosa es el valor por defecto de graphrag query y el que usa sensemaking (default del pipeline) 
lista pide la respuesta exacta de BioASQ: solo nombres, uno por linea, sin encabezado ni comentario, para que se pueda medir como conjunto. 

exacta_factoid y exacta_list son la respuesta exacta de BioASQ por tipo de pregunta, como la piden sus guias:

 - factoid: hasta 5 entidades ordenadas por confianza, 
#cita: "For each factoid question, each participating system will have to return a list* of up to 5 entity names (e.g., up to 5 names of drugs), numbers, or similar short expressions, ordered by decreasing confidence" 
https://participants-area.bioasq.org/general_information/Task14b/

 - list:  todas las entidades que responden, una sola forma de cada nombre y sin sinonimos. 
cita: "For each list question, each participating system will have to return a single list* of entity names, numbers, or similar short expressions, jointly taken to constitute a single answer"
https://participants-area.bioasq.org/general_information/Task14b/

con estos dos formatos la busqueda global no usa el prompt de reduce del proyecto sino REDUCE_EXACTO, porque el de GraphRAG
pide una respuesta explicada, con referencias y en markdown, y le gana a cualquier formato que se le pase

la busqueda global de graphRAG se responde en dos pasos: 
- Map: cada reporte de comunidad se le muestra al modelo por separado y el modelo saca de cad auno los puntos útiles para la pregunta 
- Reduce: un ultimo llamado junta todas esas partes y escribe la respuesta final 

el prompt de reduce original de Microsoft esta hecho para preguntas de tipo sense making: pide una respueta explicada y en markdown, lo cual daría lugar a respuestas contradictorios con list y factoId. es por esto que se adaptaron los prompts del reduce a la tarea 

"""
import os

FORMATOS = {
    "prosa": "Multiple Paragraphs",
    "lista": ("Only the names that answer the question, one per line, the most likely first. "
              "Start directly with the first name. No introduction, no heading, no explanations."),
    "lista_anterior": "A list of entity names, one per line, without explanations",
    "exacta_factoid": (
        "Return the exact answer only: the names of up to 5 biomedical entities that answer the question, "
        "ranked by confidence, the most likely first. Never exceed 5 names.\n"
        "- One name per line. Return ONLY the names: no sentences, no explanations, no headings, no references, "
        "no numbering, no markdown.\n"
        "- Use the shortest standard name of each entity (a gene symbol, a drug name, a disease name). "
        "Give each entity once, with a single name and without synonyms.\n"
        "- If no entity answers the question, return only the word: None\n\n"
        "Example of the expected output:\n"
        "NAME1\n"
        "NAME2"),
    "exacta_list": (
        "Return the exact answer only: the names of all the biomedical entities that answer the question, "
        "and only those.\n"
        "- One name per line. Return ONLY the names: no sentences, no explanations, no headings, no references, "
        "no numbering, no markdown.\n"
        "- Use the shortest standard name of each entity (a gene symbol, a drug name, a disease name). "
        "Give each entity once, with a single name and without synonyms.\n"
        "- Do not add entities that are related to the topic but do not answer the question itself.\n"
        "- If no entity answers the question, return only the word: None\n\n"
        "Example of the expected output:\n"
        "NAME1\n"
        "NAME2\n"
        "NAME3"),
}

#el prompt de reduce de la respuesta exacta, el mismo para el grafo entero y para la seleccion
REDUCE_EXACTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plantilla", "prompts_exacta",
                             "global_search_reduce_system_prompt.txt")
