"""Los graficos del experimento: un PDF por plano, con las celdas que corren en ese plano adentro.

Cuatro paginas por plano, todas con la misma grilla de 4x3: una fila por tipo de origen y una
columna por bin. Ver los cuatro origenes en la misma pagina es el punto de esta corrida, porque
el corte de iteraciones hay que calibrarlo para cada paso del algoritmo por separado y la
comparacion se hace a ojo sobre ejes identicos.

1. Ley de crecimiento: fraccion de semillas en la LCC del modulo contra la iteracion, arrancando
   en la iteracion 0. Las series (real, control uniforme, control apareado por clase de grado) se dibujan
   con la media de sus corridas y una banda alrededor. La banda de la real es la dispersion entre
   las anclas del bin, y sin ella una media alta no distingue "todas las corridas dan alto" de
   "una sola corrida tira del promedio".
2. Recall cruzado: la corrida real del nivel de referencia contra el nulo de semillas apareadas.
   Es la pagina donde el nulo mide lo que dice medir, porque las dos curvas arrancan en cero por
   construccion y toda la separacion la construye la expansion, a diferencia de la ley de
   crecimiento, donde buena parte de la brecha ya existe en la iteracion 0.
3. El mismo recall en los tres niveles de remocion del paper (Fig. 3E y 3F), sin nulo.
   Es donde se ve si la meseta depende de cuanto se escondio, que es lo que habilita leerla como
   criterio de corte: si dependiera, la meseta seria un artefacto del nivel elegido.
4. Tamaño de la componente conexa mayor del modulo contra la iteracion. Es la otra mitad de la
   ley de crecimiento: la fraccion de semillas dice que parte de lo que se buscaba quedo
   conectada y satura, mientras que el tamaño absoluto sigue creciendo despues de esa saturacion
   y muestra cuanto material arrastra el modulo.

Hasta el 2026-09-08 habia dos paginas mas, la conectividad del conjunto semilla antes de expandir
(Fig. 1B y 1D del paper, con datos de iteracion0.py) y la distribucion entre anclas de la fraccion
en la LCC en cinco iteraciones (Fig. 4F). Se sacaron a pedido de Ezequiel: la primera la sigue
resumiendo iteracion0_celdas.csv, y la segunda repetia la ley de crecimiento en otro formato.
Ese mismo dia se saco de la pagina de recall la linea de "esperable por azar" (rank sobre el
universo alcanzable): supone que las semillas escondidas estan en ese universo, lo que en los
planos fragmentados es falso y la hacia subir a 1 donde el recall real es 0, y el nulo apareado ya
es un control mas fuerte. Los PDF de la corrida 4 se dejaron como estaban, con la linea.

El p valor del nodo agregado no se dibuja ni se guarda (decision del 2026-09-04): es el criterio
interno con que DIAMOnD elige, no una medicion del experimento, y el paper lo descarta como
criterio de corte porque el conjunto sobre el que se calcula crece en cada iteracion. El criterio
de corte sale de la meseta del recall.

Regla de escalas: las metricas acotadas (fraccion de semillas y recall) van siempre en [0, 1] y
el eje de iteraciones va de 0 al presupuesto en todas las celdas, de modo que dos PDF cualesquiera
son comparables. La metrica absoluta (el tamaño de la componente) comparte el rango dentro de un
mismo plano, entre origenes y bins, porque entre planos los ordenes de magnitud no se parecen y
un rango comun aplastaria los planos chicos.

La comparacion real contra control es visual: las bandas. Las curvas promedio no extrapolan,
porque el presupuesto es fijo y todas las corridas miden lo mismo en el eje crudo.
"""
import os

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from celdas import CELDAS, CELDAS_POR_PLANO, PLANOS, RESULTADOS  # noqa: E402
from controles import N_SORTEOS  # noqa: E402
from corrida import PRESUPUESTO  # noqa: E402
from paso0 import BINS  # noqa: E402
from recall import FRAC_CON_CONTROL, FRACCIONES_ESCONDIDAS, N_FOLDS  # noqa: E402
from runner import DIR_RECALLS, DIR_TRAZAS, _ruta  # noqa: E402

DIR_GRAFICOS = os.path.join(RESULTADOS, "graficos")

COLOR_REAL = "#D55E00"      #paleta Okabe-Ito: distinguible con daltonismo y en blanco y negro
COLOR_APAREADO = "#0072B2"
COLOR_UNIFORME = "#009E73"

#los tres niveles de remocion comparten color (los tres son la corrida real) y se distinguen por
#el trazo: lo que la lamina tiene que mostrar es que las tres curvas van juntas, y tres colores
#invitarian a leerlas como tres series distintas
TRAZO_POR_FRACCION = {0.1: ":", 0.2: "--", 0.3: "-"}

#las filas de cada grilla son las celdas que corren en el plano, en el orden de CELDAS_POR_PLANO.
#En la version de OptimusKG eran los cuatro tipos de origen; aca cada plano tiene una sola celda


def cargar_casos_corridos(celda_nombre):
    """Los casos de casos.csv de esta celda que ya tienen traza y recall en disco.

    Sin casos.csv (todavia no corrio el paso 0) no hay nada corrido, por definicion.
    """
    ruta_casos = os.path.join(RESULTADOS, "casos.csv")
    if not os.path.exists(ruta_casos):
        return pd.DataFrame(columns=["celda", "ancla", "n_semillas", "bin", "seed"])
    casos = pd.read_csv(ruta_casos)
    casos = casos[casos["celda"] == celda_nombre]
    if casos.empty:
        return casos
    celda = CELDAS[celda_nombre]
    con_datos = [os.path.exists(_ruta(DIR_TRAZAS, celda, a))
                 and os.path.exists(_ruta(DIR_RECALLS, celda, a))
                 for a in casos["ancla"]]
    return casos[con_datos]


def arrastrar_hasta_el_presupuesto(tabla, columna_paso, columnas_vaciadas,
                                   presupuesto=PRESUPUESTO):
    """Completa hasta el presupuesto las corridas que agotaron la red antes, repitiendo su ultima fila. Cuando la red se agota el modulo deja de cambiar, asi que los acumulados (fraccion de semillas en la LCC, tamaño de la LCC, recall) son constantes de ahi en adelante y arrastrarlos reproduce lo que el algoritmo habria reportado. Sin esto, toda agregacion por iteracion se calcula solo sobre las corridas que sobrevivieron hasta ese punto. Lo que describe al nodo agregado (nodo, grado, kb) no existe en esas filas y se vacia. Las filas agregadas llevan arrastrada = True."""
    claves = [c for c in ("ancla", "fuente", "sorteo", "frac_escondida", "fold")
              if c in tabla.columns]
    tabla = tabla.copy()
    tabla["arrastrada"] = False
    if tabla.empty:
        return tabla
    ultimas = tabla.loc[tabla.groupby(claves, sort=False)[columna_paso].idxmax()]
    cortas = ultimas[ultimas[columna_paso] < presupuesto]
    if cortas.empty:
        return tabla
    faltantes = (presupuesto - cortas[columna_paso]).to_numpy(dtype=int)
    relleno = cortas.loc[cortas.index.repeat(faltantes)].copy()
    relleno[columna_paso] = np.concatenate(
        [np.arange(ultimo + 1, presupuesto + 1) for ultimo in cortas[columna_paso]])
    for columna in columnas_vaciadas:
        if columna in relleno.columns:
            relleno[columna] = np.nan
    relleno["arrastrada"] = True
    return pd.concat([tabla, relleno], ignore_index=True)


def cargar_trazas(celda_nombre, casos):
    """Todas las trazas de los casos, con ancla y bin como columnas y las corridas truncadas arrastradas hasta el presupuesto."""
    celda = CELDAS[celda_nombre]
    partes = []
    for _, fila in casos.iterrows():
        traza = pd.read_parquet(_ruta(DIR_TRAZAS, celda, fila["ancla"]))
        traza["ancla"] = fila["ancla"]
        traza["bin"] = fila["bin"]
        partes.append(traza)
    if not partes:
        return pd.DataFrame()
    return arrastrar_hasta_el_presupuesto(pd.concat(partes, ignore_index=True), "iteracion",
                                          ("nodo", "grado", "kb"))


CLAVES_DE_FOLD = ["ancla", "fuente", "sorteo", "frac_escondida"]


def completar_folds_ausentes(curvas, n_folds=N_FOLDS, presupuesto=PRESUPUESTO):
    """Agrega con recall cero los folds que no dejaron filas. Un fold sin filas es uno en que DIAMOnD no agrego ningun nodo, porque las visibles no tenian frontera: su recall es cero en todo el recorrido, y si se lo deja afuera la media del bin sube. Las escondidas y el universo se copian de otro fold del mismo grupo, que los comparte. Un grupo sin ningun fold en disco no se puede completar y queda afuera.

    El grupo es (ancla, fuente, sorteo, nivel de remocion): cada combinacion tiene su propia
    tanda de N_FOLDS folds, y un fold ausente en una no dice nada de las otras.
    """
    if curvas.empty:
        return curvas
    relleno = []
    for valores, del_grupo in curvas.groupby(CLAVES_DE_FOLD, sort=False):
        presentes = set(del_grupo["fold"])
        modelo = del_grupo.iloc[0]
        for fold in range(n_folds):
            if fold in presentes:
                continue
            fila = dict(zip(CLAVES_DE_FOLD, valores))
            fila.update({
                "fold": fold, "rank": np.arange(1, presupuesto + 1), "recall": 0.0,
                "n_escondidas": modelo["n_escondidas"], "n_universo": modelo["n_universo"],
                "bin": modelo["bin"], "arrastrada": True})
            relleno.append(pd.DataFrame(fila))
    if not relleno:
        return curvas
    return pd.concat([curvas, *relleno], ignore_index=True)


def cargar_recalls(celda_nombre, casos):
    """Todas las curvas de recall de los casos, con ancla y bin como columnas, los folds truncados arrastrados hasta el presupuesto y los folds sin filas completados con recall cero."""
    celda = CELDAS[celda_nombre]
    partes = []
    for _, fila in casos.iterrows():
        curva = pd.read_parquet(_ruta(DIR_RECALLS, celda, fila["ancla"]))
        curva["ancla"] = fila["ancla"]
        curva["bin"] = fila["bin"]
        partes.append(curva)
    if not partes:
        return pd.DataFrame()
    curvas = pd.concat(partes, ignore_index=True)
    #la primera corrida guardo un solo nivel de remocion y ninguna fuente, porque el recall no
    #tenia control todavia. Se la lee poniendo esos valores, asi sus PDF se pueden regenerar
    if "fuente" not in curvas.columns:
        curvas["fuente"] = "real"
        curvas["sorteo"] = 0
        curvas["frac_escondida"] = FRAC_CON_CONTROL
    curvas = arrastrar_hasta_el_presupuesto(curvas, "rank", ())
    return completar_folds_ausentes(curvas)


def curva_promedio(trazas, columna):
    """Media de la columna por iteracion, sobre las corridas presentes.

    No extrapola: el presupuesto es fijo y todas las corridas llegan a las mismas iteraciones.
    """
    return trazas.groupby("iteracion")[columna].mean()


def banda_de_corridas(trazas, columna):
    """(media, desvio) por iteracion entre las corridas de un conjunto.

    Una corrida es un par (ancla, sorteo), asi que la banda de un control resume sus sorteos
    sobre todas las anclas del bin, y la de las corridas reales (donde el sorteo es siempre 0)
    resume la dispersion entre anclas. Las dos bandas miden lo mismo, dispersion entre corridas,
    que es lo que las hace comparables a ojo.
    """
    por_corrida = trazas.groupby(["ancla", "sorteo", "iteracion"])[columna].mean()
    ancho = por_corrida.unstack("iteracion")   #una fila por corrida
    return ancho.mean(axis=0), ancho.std(axis=0)


#nombre alternativo, porque el resumen pide explicitamente la banda de un control
banda_control = banda_de_corridas


def vecinos_del_bin(trazas_del_bin):
    """Rango y mediana de vecinos de la capa B (semillas) de las anclas del bin, leidos de la corrida real y no de casos.csv, que en una comparacion pareada puede traer los de otra version."""
    #cambio respecto de optimuskg: el titulo de cada panel dice cuantos vecinos tienen sus anclas
    por_ancla = trazas_del_bin[trazas_del_bin["fuente"] == "real"].groupby("ancla")["n_semillas"].first()
    return f"{por_ancla.min():.0f} a {por_ancla.max():.0f} vecinos, mediana {por_ancla.median():g}"


def nulo_gana(del_bin, columna="frac_semillas_lcc"):
    """{"apareado": n (si esta), "uniforme": n (si esta), "casos": total}: en cuantas anclas del
    bin el area bajo la curva del nulo iguala o supera a la de la corrida real.

    Se compara caso por caso, cada ancla contra el promedio de sus propios sorteos, asi que el
    numero no depende de la forma de las distribuciones ni se deja arrastrar por unos pocos casos
    extremos, como si pasa con la media del bin. Se usa el area y no el valor final porque mira
    todo el recorrido: en las celdas que saturan temprano muchas corridas empatan en el ultimo
    punto. El empate cuenta para el nulo, asi que el numero queda del lado conservador para
    DIAMOnD. Un bin sin señal deberia repartir los casos en mitades. Cada nulo aparece solo si la
    traza lo tiene, asi que una corrida con otros nulos (la corrida 2 tenia reordenado) se lee
    sin romper: la base del conteo de casos es el apareado, y sin el los casos quedan en cero.
    """
    areas = {}
    for fuente in ("real", "apareado", "uniforme"):
        de_la_fuente = del_bin[del_bin["fuente"] == fuente]
        if de_la_fuente.empty:
            continue
        por_corrida = de_la_fuente.groupby(["ancla", "sorteo", "iteracion"])[columna].mean()
        areas[fuente] = (por_corrida.unstack("iteracion").mean(axis=1)
                         .groupby(level="ancla").mean())
    base = "apareado"
    comunes = areas["real"].index.intersection(areas[base].index) if base in areas else areas["real"].index[:0]
    resultado = {"casos": len(comunes)}
    for fuente in ("apareado", "uniforme"):
        if fuente not in areas:
            continue
        comunes_f = areas["real"].index.intersection(areas[fuente].index)
        resultado[fuente] = int((areas[fuente][comunes_f] >= areas["real"][comunes_f]).sum())
    return resultado


def _rotulo_origen(celda_nombre):
    """El nombre de la fila: de que tipo es el ancla y por que relacion cosecha sus semillas.

    Va partido en lineas cortas porque se dibuja rotado noventa grados sobre el alto de un
    panel, y una linea larga se desborda hacia las filas vecinas.
    """
    celda = CELDAS[celda_nombre]
    lineas = [f"origen {celda.origen}", f"cosecha por {celda.relacion_cosecha}"]
    if celda.ancla_en_la_red:
        lineas.append("ancla excluida")
    return "\n".join(lineas)


def _banda(eje, media, desvio, color, etiqueta, clip=None):
    """Una banda de un desvio alrededor de la media, tenue y con los bordes punteados.

    La opacidad baja con borde marcado es lo que deja convivir dos bandas en el mismo panel: el
    relleno da la sensacion de area y el borde la delimita donde se solapan. `clip` recorta la
    banda al rango valido de la metrica: una fraccion no puede superar 1, y dibujar banda donde
    no puede haber observaciones exagera la dispersion.
    """
    piso, techo = media - desvio, media + desvio
    if clip is not None:
        piso = piso.clip(lower=clip[0], upper=clip[1])
        techo = techo.clip(lower=clip[0], upper=clip[1])
    eje.fill_between(media.index, piso, techo, alpha=0.12, color=color, label=etiqueta,
                     linewidth=0)
    for borde in (piso, techo):
        eje.plot(borde.index, borde, color=color, linewidth=0.5, linestyle="--", alpha=0.75)


def _texto_panel_vacio(celda_nombre):
    """Que decir en un panel sin datos. Si la celda quedo sin pool en el paso 0, el motivo que este dejo en celdas_sin_pool.csv, porque eso es un resultado del experimento y no una corrida que falta; si no, que sus casos no corrieron todavia."""
    ruta = os.path.join(RESULTADOS, "celdas_sin_pool.csv")
    if os.path.exists(ruta):
        sin_pool = pd.read_csv(ruta)
        motivos = dict(zip(sin_pool["celda"], sin_pool["motivo"]))
        if celda_nombre in motivos:
            return "sin pool en el paso 0:\n" + motivos[celda_nombre].replace(", cuando", ",\ncuando")
    return "sin corridas"


def _panel_vacio(eje, texto):
    """Un panel de una celda sin datos.

    Solo escribe el aviso: los ticks se dejan como estan porque los ejes de la grilla son
    compartidos, y vaciarlos aca se los borraria tambien a los paneles que si tienen curvas.
    """
    eje.text(0.5, 0.5, texto, ha="center", va="center", transform=eje.transAxes, fontsize=8,
             color="#7f8c8d")


def _grilla_origenes(fig, trazas_por_celda, plano, columna, titulo, ylabel,
                     ylim=None, con_conteo=False, clip=None):
    """La grilla de las paginas por iteracion (una fila por tipo de origen, tres columnas): filas = tipo de origen, columnas = bin.

    `ylim` puede ser un par fijo (metricas acotadas) o None, y en ese caso el rango se comparte
    entre todos los paneles de la pagina, que es lo que hace comparables los cuatro origenes.
    Con `con_conteo`, cada panel anota en cuantos casos el nulo le gana a la corrida real: es el
    resumen que se puede leer aun donde las bandas se superponen, que es justamente donde no hay
    señal.
    """
    filas_grilla = CELDAS_POR_PLANO[plano]
    ejes = fig.subplots(len(filas_grilla), 3, squeeze=False, sharex=True, sharey=True)
    for fila, celda_nombre in enumerate(filas_grilla):
        trazas = trazas_por_celda.get(celda_nombre)
        for columna_i, nombre_bin in enumerate(BINS):
            eje = ejes[fila][columna_i]
            if trazas is not None and not trazas.empty:
                del_bin = trazas[trazas["bin"] == nombre_bin]
            else:
                del_bin = pd.DataFrame()
            if del_bin.empty:
                _panel_vacio(eje, _texto_panel_vacio(celda_nombre))
                continue

            #el uniforme se reporta como linea sola: dos distribuciones rellenas por panel es el
            #limite legible, y la dispersion del control debil no participa de ninguna decision
            media_u, _ = banda_de_corridas(del_bin[del_bin["fuente"] == "uniforme"], columna)
            eje.plot(media_u.index, media_u, color=COLOR_UNIFORME, linewidth=1.1,
                     linestyle="-", label="control uniforme (media)")
            #el apareado por clase de grado es el nulo fuerte y lleva banda. Si la traza no lo
            #trae (la corrida 2 tenia reordenado en su lugar) la banda simplemente no se dibuja
            apareadas = del_bin[del_bin["fuente"] == "apareado"]
            if not apareadas.empty:
                media, desvio = banda_de_corridas(apareadas, columna)
                _banda(eje, media, desvio, COLOR_APAREADO,
                       "semillas apareadas por clase de grado (media y dispersión)", clip)
                eje.plot(media.index, media, color=COLOR_APAREADO, linewidth=0.9)
            real, desvio_real = banda_de_corridas(del_bin[del_bin["fuente"] == "real"], columna)
            if desvio_real.notna().any():
                _banda(eje, real, desvio_real, COLOR_REAL,
                       "real (dispersión entre las anclas)", clip)
            eje.plot(real.index, real, color=COLOR_REAL, linewidth=1.8,
                     label="real (media del bin)")

            n_casos = del_bin["ancla"].nunique()
            eje.set_xlim(0, PRESUPUESTO)
            if ylim is not None:
                eje.set_ylim(*ylim)
            titulo_bin = (f"bin {nombre_bin} ({n_casos} {'caso' if n_casos == 1 else 'casos'}, "
                          f"{vecinos_del_bin(del_bin)})")
            if con_conteo:
                #el conteo va como subtitulo del panel: el titulo se empuja hacia arriba con pad
                #y el subtitulo entra en la franja que queda, sin pisar ninguna curva
                conteo = nulo_gana(del_bin, columna)
                subtitulo = (f"el nulo gana en {conteo.get('apareado', 0)} de {conteo['casos']} "
                             f"(apareado) y {conteo.get('uniforme', 0)} (uniforme)")
                #la fraccion de semillas de control que salio de una clase de grado vecina va en
                #el mismo subtitulo: es la medida de cuan bien apareado esta el nulo de este panel
                if "semillas_fuera_de_clase" in apareadas.columns and not apareadas.empty:
                    por_corrida = apareadas.groupby(["ancla", "sorteo"]).first()
                    fuera = (por_corrida["semillas_fuera_de_clase"] / por_corrida["n_semillas"]).mean()
                    if pd.notna(fuera):
                        subtitulo += f" | fuera de clase {100 * fuera:.0f}%"
                eje.set_title(titulo_bin, fontsize=8, pad=12)
                eje.text(0.5, 1.015, subtitulo,
                         transform=eje.transAxes, ha="center", fontsize=6, color="#444444")
            else:
                eje.set_title(titulo_bin, fontsize=8)
            if fila == len(filas_grilla) - 1:
                eje.set_xlabel("iteración")
            if fila == 0 and columna_i == 0:
                eje.legend(fontsize=6.5)

        #el rotulo de fila va pegado al panel. El nombre de la metrica es un solo texto de
        #figura, para que no compita con el rotulo por el mismo margen
        ejes[fila][0].annotate(_rotulo_origen(celda_nombre), xy=(0, 0.5), xytext=(-34, 0),
                               xycoords="axes fraction", textcoords="offset points",
                               rotation=90, va="center", ha="center", fontsize=6.5,
                               weight="bold", linespacing=1.4)
    fig.supylabel(ylabel, fontsize=9)
    fig.suptitle(titulo)
    if con_conteo:
        fig.text(0.01, 0.005, f"el nulo gana = el promedio de su curva a lo largo de las "
                 f"{PRESUPUESTO} iteraciones iguala o supera al de la corrida real de esa ancla "
                 f"(promediando sus {N_SORTEOS} sorteos). El empate cuenta para el nulo",
                 fontsize=6, color="#444444")
    #deja lugar arriba para el titulo general y a la izquierda para los rotulos de fila
    fig.tight_layout(rect=(0.075, 0.02 if con_conteo else 0, 1, 0.95))


def curva_de_recall_media(curvas):
    """(media por rank entre las anclas, semiancho del IC95 entre anclas).

    Se promedia primero dentro de cada ancla y recien despues entre anclas. Los folds de una
    misma ancla esconden semillas del mismo conjunto, asi que no son observaciones
    independientes: contarlos como tales angosta el intervalo sin que haya mas informacion.
    """
    por_ancla = curvas.groupby(["ancla", "rank"])["recall"].mean()
    por_rank = por_ancla.groupby("rank")
    n = por_rank.count()
    return por_rank.mean(), 1.96 * por_rank.std() / np.sqrt(n)


def _pagina_recall(fig, recalls_por_celda, plano, titulo, niveles=(FRAC_CON_CONTROL,),
                   con_nulo=True, vecinos_por_celda=None):
    """La grilla 4x3 del recall cruzado, con los niveles de remocion que se le pidan.

    Con `niveles` en el nivel de referencia solo y `con_nulo`, arma la pagina de comparacion: una
    curva real contra el nulo de semillas apareadas. Con los tres niveles y sin nulo arma la
    pagina que responde si la meseta depende de cuanto se escondio. Se
    separan en dos paginas porque son dos preguntas distintas y seis series en un mismo panel no
    se leen proyectadas.

    Los niveles comparten color y se distinguen por el trazo: lo que hay que ver es si van
    juntas, y tres colores invitarian a leerlas como tres series independientes.
    """
    filas_grilla = CELDAS_POR_PLANO[plano]
    ejes = fig.subplots(len(filas_grilla), 3, squeeze=False, sharex=True, sharey=True)
    for fila, celda_nombre in enumerate(filas_grilla):
        recalls = recalls_por_celda.get(celda_nombre)
        for columna_i, nombre_bin in enumerate(BINS):
            eje = ejes[fila][columna_i]
            if recalls is not None and not recalls.empty:
                del_bin = recalls[recalls["bin"] == nombre_bin]
            else:
                del_bin = pd.DataFrame()
            if del_bin.empty:
                _panel_vacio(eje, _texto_panel_vacio(celda_nombre))
                continue

            #el nulo va primero para que las curvas reales queden dibujadas por encima de su banda
            del_nulo = del_bin[del_bin["fuente"] == "apareado"] if con_nulo else pd.DataFrame()
            if not del_nulo.empty:
                media_nulo, ic_nulo = curva_de_recall_media(del_nulo)
                _banda(eje, media_nulo, ic_nulo, COLOR_APAREADO,
                       "semillas apareadas por clase de grado (IC95)", (0, 1))
                eje.plot(media_nulo.index, media_nulo, color=COLOR_APAREADO, linewidth=0.9)

            for frac in niveles:
                del_nivel = del_bin[(del_bin["fuente"] == "real")
                                    & (del_bin["frac_escondida"] == frac)]
                if del_nivel.empty:
                    continue
                media, ic95 = curva_de_recall_media(del_nivel)
                eje.plot(media.index, media, color=COLOR_REAL, linewidth=1.5,
                         linestyle=TRAZO_POR_FRACCION[frac],
                         label=f"real, {round(frac * 100)}% escondido")
                if frac == FRAC_CON_CONTROL:
                    _banda(eje, media, ic95, COLOR_REAL, "IC95 entre anclas", (0, 1))

            eje.set_xlim(0, PRESUPUESTO)
            eje.set_ylim(0, 1)
            #los recalls no guardan cuantas semillas tenia el caso, el texto viene armado desde las trazas
            vecinos = (vecinos_por_celda or {}).get(celda_nombre, {}).get(nombre_bin)
            eje.set_title(f"bin {nombre_bin} ({vecinos})" if vecinos else f"bin {nombre_bin}", fontsize=8)
            if fila == len(filas_grilla) - 1:
                eje.set_xlabel("rank (nodos agregados)")
            if fila == 0 and columna_i == 0:
                eje.legend(fontsize=6)

        rotulo = _rotulo_origen(celda_nombre)
        if CELDAS[celda_nombre].ancla_en_la_red:
            rotulo += "\nrecall contra los controles"
        ejes[fila][0].annotate(rotulo, xy=(0, 0.5), xytext=(-34, 0),
                               xycoords="axes fraction", textcoords="offset points",
                               rotation=90, va="center", ha="center", fontsize=6.5,
                               weight="bold", linespacing=1.4)
    fig.supylabel("recall de semillas escondidas", fontsize=9)
    fig.suptitle(titulo)
    #deja lugar arriba para el titulo general y a la izquierda para los rotulos de fila
    fig.tight_layout(rect=(0.075, 0, 1, 0.95))


def grafico_plano(plano_nombre):
    """El PDF de un plano, con sus tipos de origen en cada pagina."""
    trazas_por_celda = {}
    recalls_por_celda = {}
    total_casos = 0
    for celda_nombre in CELDAS_POR_PLANO[plano_nombre]:
        casos = cargar_casos_corridos(celda_nombre)
        if casos.empty:
            continue
        trazas_por_celda[celda_nombre] = cargar_trazas(celda_nombre, casos)
        recalls_por_celda[celda_nombre] = cargar_recalls(celda_nombre, casos)
        total_casos += len(casos)

    if not trazas_por_celda:
        print(f"[plano {plano_nombre}] sin casos corridos, salteado")
        return None

    os.makedirs(DIR_GRAFICOS, exist_ok=True)
    ruta = os.path.join(DIR_GRAFICOS, f"{plano_nombre}.pdf")
    relacion = PLANOS[plano_nombre].relacion

    vecinos_por_celda = {
        celda_nombre: {b: vecinos_del_bin(trazas[trazas["bin"] == b])
                       for b in BINS if not trazas[trazas["bin"] == b].empty}
        for celda_nombre, trazas in trazas_por_celda.items()}

    with PdfPages(ruta) as pdf:
        fig = plt.figure(figsize=(13, 3.2 * len(CELDAS_POR_PLANO[plano_nombre]) + 1))
        _grilla_origenes(fig, trazas_por_celda, plano_nombre, "frac_semillas_lcc",
                         f"plano {plano_nombre} ({relacion}): ley de crecimiento y fracción de "
                         f"semillas en la LCC del módulo", "frac. de semillas en la LCC",
                         ylim=(0, 1), con_conteo=True, clip=(0, 1))
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=(13, 3.2 * len(CELDAS_POR_PLANO[plano_nombre]) + 1))
        _pagina_recall(fig, recalls_por_celda, plano_nombre,
                       f"plano {plano_nombre} ({relacion}): recall cruzado contra el nulo de "
                       f"semillas apareadas", vecinos_por_celda=vecinos_por_celda)
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=(13, 3.2 * len(CELDAS_POR_PLANO[plano_nombre]) + 1))
        _pagina_recall(fig, recalls_por_celda, plano_nombre,
                       f"plano {plano_nombre} ({relacion}): recall cruzado en los tres niveles "
                       f"de remoción", niveles=FRACCIONES_ESCONDIDAS, con_nulo=False,
                       vecinos_por_celda=vecinos_por_celda)
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=(13, 3.2 * len(CELDAS_POR_PLANO[plano_nombre]) + 1))
        _grilla_origenes(fig, trazas_por_celda, plano_nombre, "lcc_tam",
                         f"plano {plano_nombre} ({relacion}): tamaño de la componente conexa "
                         f"mayor del módulo", "nodos en la componente conexa mayor",
                         con_conteo=True, clip=(0, None))
        pdf.savefig(fig)
        plt.close(fig)

    print(f"[plano {plano_nombre}] gráficos: {ruta} ({total_casos} casos)")
    return ruta


def main():
    for plano_nombre in PLANOS:
        grafico_plano(plano_nombre)


if __name__ == "__main__":
    main()
