"""Renderizadores de QGIS a partir de la simbología de Geosian.

``styles`` decide qué color lleva cada caso; aquí se monta el renderizador que
lo pinta. Los tamaños imitan a las teselas del frontal, que los dan en metros
con topes en píxeles: los puntos tienen 6 m de radio, entre 3 y 6 px, y las
líneas 1 m de grosor, entre 1 y 3 px. Así de lejos no tapan el mapa y de cerca
crecen con él. Los contornos van a 1 px fijo.
"""

import math

from qgis.core import (
    Qgis,
    QgsColorRampLegendNodeSettings,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsHeatmapRenderer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsNullSymbolRenderer,
    QgsPalLayerSettings,
    QgsProperty,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
    QgsSvgMarkerSymbolLayer,
    QgsSymbolLayer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayerSimpleLabeling,
    QgsVectorTileBasicRenderer,
    QgsVectorTileBasicRendererStyle,
)
from qgis.PyQt.QtGui import QColor

from . import schema as S
from . import styles

# Diámetro del punto en metros y sus topes en píxeles; grosor de línea igual.
POINT_SIZE_M = 12
POINT_MIN_PX = 6
POINT_MAX_PX = 12
LINE_WIDTH_M = 1
LINE_MIN_PX = 1
LINE_MAX_PX = 3
OUTLINE_WIDTH_PX = 1

# Metros por píxel a escala 1:1 con 96 ppp (0,0254 m / 96).
_M_POR_PX = 0.0254 / 96


def _px_desde_metros(metros, minimo, maximo):
    """Expresión que da en píxeles un tamaño en metros, con topes.

    Se calcula con la escala del mapa en vez de usar la unidad «metros a
    escala» de QGIS porque la leyenda no aplica los topes de esa unidad y
    dibujaba los puntos como círculos enormes. Así el mapa crece y mengua como
    en la web, y la leyenda usa el tamaño fijo del símbolo.
    """
    return f"clamp({minimo}, {metros} / (@map_scale * {_M_POR_PX:.10f}), {maximo})"


def _rgba(color):
    return ",".join(str(int(c)) for c in color)


def make_symbol(familia, color):
    """Símbolo de QGIS para un color de relleno de Geosian."""
    borde = styles.stroke_of(color)
    if familia == "point":
        simbolo = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": _rgba(color),
                "outline_color": _rgba(borde),
                "outline_width": str(OUTLINE_WIDTH_PX),
                "outline_width_unit": "Pixel",
            }
        )
        capa = simbolo.symbolLayer(0)
        capa.setSize(POINT_MAX_PX)
        capa.setSizeUnit(QgsUnitTypes.RenderPixels)
        capa.setDataDefinedProperty(
            QgsSymbolLayer.PropertySize,
            QgsProperty.fromExpression(_px_desde_metros(POINT_SIZE_M, POINT_MIN_PX, POINT_MAX_PX)),
        )
        return simbolo
    if familia == "line":
        # En las teselas del frontal la línea va con el color oscurecido.
        simbolo = QgsLineSymbol.createSimple({"line_color": _rgba(borde)})
        capa = simbolo.symbolLayer(0)
        capa.setWidth(2)
        capa.setWidthUnit(QgsUnitTypes.RenderPixels)
        capa.setDataDefinedProperty(
            QgsSymbolLayer.PropertyStrokeWidth,
            QgsProperty.fromExpression(_px_desde_metros(LINE_WIDTH_M, LINE_MIN_PX, LINE_MAX_PX)),
        )
        return simbolo
    return QgsFillSymbol.createSimple(
        {
            "color": _rgba(color),
            "outline_color": _rgba(borde),
            "outline_width": str(OUTLINE_WIDTH_PX),
            "outline_width_unit": "Pixel",
        }
    )


# Halo blanco detrás del icono, como en la web: el mismo dibujo, un 18 % mayor.
HALO_COLOR = (255, 255, 255, 235)
HALO_SCALE = 1.18


# El blanco del halo en la vía GeoJSON de la web (``createViewIconLayer``).
HALO_COLOR_GEOJSON = (255, 255, 255, 230)


def make_icon_symbol(ruta_svg, color, size=24, size_min=16, size_max=48, por_teselas=True):
    """Marcador con el icono de una vista, teñido con ``color``.

    El tamaño sigue a la web, que tiene dos caminos. Por teselas
    (``mvtLayerGenerator.js``): ``size`` metros, acotado entre ``max(8, size_min / 2)``
    y ``size`` píxeles. En GeoJSON (``createViewIconLayer``): ``size`` píxeles fijos,
    acotados entre ``size_min`` y ``size_max``.
    """
    simbolo = QgsMarkerSymbol()
    simbolo.deleteSymbolLayer(0)
    if por_teselas:
        minimo = max(8.0, size_min * 0.5)
        expresion = _px_desde_metros(size, minimo, size)
        halo = HALO_COLOR
    else:
        fijo = min(max(size, size_min), size_max)
        expresion = None
        halo = HALO_COLOR_GEOJSON
    for escala, relleno in ((HALO_SCALE, halo), (1.0, color)):
        capa = QgsSvgMarkerSymbolLayer(ruta_svg, (size if por_teselas else fijo) * escala)
        capa.setSizeUnit(QgsUnitTypes.RenderPixels)
        capa.setFillColor(QColor(*relleno))
        capa.setStrokeWidth(0)
        if expresion:
            capa.setDataDefinedProperty(
                QgsSymbolLayer.PropertySize,
                QgsProperty.fromExpression(f"({expresion}) * {escala}"),
            )
        simbolo.appendSymbolLayer(capa)
    return simbolo


def field_resolver(fields, attr_map):
    """Traduce un nombre de atributo del LAD al nombre de campo en la capa.

    Devuelve ``None`` si la capa no tiene ese campo. Una ruta con puntos
    (``surface_type.tipo``) solo casa si hay un campo que se llame
    exactamente así: el frontal (``getNestedAttributeValue``) la busca como
    objeto anidado en el elemento y, si no existe, no hay valor y se pinta el
    color por defecto. Quedarse con el último tramo, como se hacía antes,
    coloreaba en QGIS capas que en la web salen con el color por defecto
    (Tipo de superficie de Melilla).
    """
    por_atributo = {}
    for nombre, attr in (attr_map or {}).items():
        if isinstance(attr, dict) and attr.get("name"):
            por_atributo.setdefault(str(attr["name"]), nombre)
    nombres = {fields.at(i).name() for i in range(fields.count())}

    def resolver(atributo):
        atributo = str(atributo or "")
        if atributo in por_atributo:
            return por_atributo[atributo]
        if atributo in nombres:
            return atributo
        return None

    return resolver


def base_renderer(schema, geometry_type, resolver):
    """Renderizador del estilo base de la capa (``schema.styles``).

    Returns:
        ``(renderizador, avisos)``. Los avisos dicen qué reglas no se pudieron
        aplicar porque la capa no tiene el campo.
    """
    familia = styles.geometry_family(geometry_type)
    estilo = styles.base_style(schema, geometry_type)
    return _rules_renderer(familia, estilo, resolver)


def _rules_renderer(familia, estilo, resolver, fabrica=None):
    fabrica = fabrica or (lambda color: make_symbol(familia, color))
    avisos = []
    if not estilo["rules"]:
        return QgsSingleSymbolRenderer(fabrica(estilo["default"])), avisos

    raiz = QgsRuleBasedRenderer.Rule(None)
    sin_campo = set()
    for regla in estilo["rules"]:
        campo = resolver(regla["attribute"])
        if campo is None:
            sin_campo.add(regla["attribute"])
            continue
        partes = [styles.match_expression(campo, regla["value"])]
        for atributo, valores in regla["excluded"]:
            otro = resolver(atributo)
            if otro is None:
                continue
            lista = ", ".join(S._quote_value(v) for v in valores)
            partes.append(
                f"(to_string({S._quote_field(otro)}) IS NULL"
                f" OR to_string({S._quote_field(otro)}) NOT IN ({lista}))"
            )
        hijo = QgsRuleBasedRenderer.Rule(
            fabrica(regla["color"]),
            filterExp=" AND ".join(partes),
            label=regla["label"],
        )
        raiz.appendChild(hijo)

    for atributo in sorted(sin_campo):
        avisos.append(f"La regla de color sobre «{atributo}» no se aplica: la capa no tiene ese campo.")

    # Si ninguna regla se pudo aplicar, todo cae en el color por defecto, como
    # en la web cuando no encuentra el valor: un símbolo único, sin «Otros».
    if not raiz.children():
        return QgsSingleSymbolRenderer(fabrica(estilo["default"])), avisos

    resto = QgsRuleBasedRenderer.Rule(
        fabrica(estilo["default"]), label=estilo["default_label"] or "Otros"
    )
    resto.setIsElse(True)
    raiz.appendChild(resto)
    return QgsRuleBasedRenderer(raiz), avisos


def view_renderer(style_config, geometry_type, schema, resolver, iconos=None, teselas=True):
    """Renderizador del ``style_config`` de una vista.

    Args:
        iconos: ``(lib, nombre) -> ruta del SVG o None``, para las vistas con
            icono. Sin él, o si el icono no se puede conseguir, se pintan
            círculos.
        teselas: si la web lleva la capa por teselas (``styles.load_mode``).

    Returns:
        ``(renderizador, avisos)``.
    """
    familia = styles.geometry_family(geometry_type)
    vista = styles.view_style(style_config, geometry_type, schema, teselas)
    avisos = []
    if vista["kind"] == "none":
        return QgsNullSymbolRenderer(), ["La vista es de iconos y no tiene icono: la web no la pinta."]
    if vista.get("unsupported"):
        avisos.append(
            f"La visualización «{vista['unsupported']}» de la vista no existe en QGIS; "
            "se pinta con sus colores."
        )

    def fabrica(color):
        return make_symbol(familia, color)

    icono = vista.get("icon")
    if icono and familia == "point":
        ruta = iconos(icono["lib"], icono["name"]) if iconos else None
        if ruta:
            def fabrica(color):  # el icono sustituye al círculo
                return make_icon_symbol(ruta, color, icono["size"], icono["size_min"],
                                        icono["size_max"], icono["por_teselas"])
        else:
            avisos.append(
                f"No se pudo conseguir el icono «{icono['name']}»; se pintan círculos."
            )

    tipo = vista["kind"]
    if tipo == "base":
        renderizador, mas = _rules_renderer(familia, vista["base_fallback"], resolver, fabrica)
        return renderizador, avisos + mas

    if tipo == "single":
        return QgsSingleSymbolRenderer(fabrica(vista["color"])), avisos

    if tipo == "categorized":
        campo = resolver(vista["attribute"])
        if campo is None:
            avisos.append(
                f"La vista colorea por «{vista['attribute']}», que la capa no tiene; "
                "se pinta con el color por defecto."
            )
            return QgsSingleSymbolRenderer(fabrica(vista["default"])), avisos
        estilo = {
            "rules": [
                {"attribute": vista["attribute"], "value": v, "color": c, "label": e, "excluded": []}
                for v, c, e in vista["categories"]
            ],
            "default": vista["default"],
            "default_label": vista["default_label"],
        }
        renderizador, mas = _rules_renderer(familia, estilo, resolver, fabrica)
        return renderizador, avisos + mas

    if tipo == "graduated":
        campo = resolver(vista["attribute"])
        if campo is None:
            avisos.append(f"La vista gradúa por «{vista['attribute']}», que la capa no tiene.")
            return QgsSingleSymbolRenderer(fabrica(vista["default"])), avisos
        if not vista["ranges"] and not vista["ramp"]:
            return QgsSingleSymbolRenderer(fabrica(vista["default"])), avisos
        # Reglas y no tramos de QGIS: los de QGIS cierran por arriba (10 cae en 0-10)
        # y no pintan lo que no es número; la web cierra por abajo y lo pinta del
        # color por omisión.
        valor = f"to_real({S._quote_field(campo)})"
        raiz = QgsRuleBasedRenderer.Rule(None)
        for desde, hasta, color, etiqueta in vista["ranges"]:
            limites = [f"{valor} >= {S._number(desde)}" if desde is not None else None,
                       f"{valor} < {S._number(hasta)}" if hasta is not None else None]
            filtro = " AND ".join(x for x in limites if x)
            raiz.appendChild(QgsRuleBasedRenderer.Rule(fabrica(color), filterExp=filtro, label=etiqueta))
        if vista["ramp"]:
            paradas, minimo, maximo = vista["ramp"]
            simbolo = fabrica(paradas[len(paradas) // 2] + (styles.DEFAULT_ALPHA,))
            _color_calculado(simbolo, familia, _rampa_continua(valor, paradas, minimo, maximo))
            raiz.appendChild(QgsRuleBasedRenderer.Rule(
                simbolo, filterExp=f"{valor} IS NOT NULL",
                label=f"{styles._js_numero(minimo)} - {styles._js_numero(maximo)}"))
        resto = QgsRuleBasedRenderer.Rule(fabrica(vista["default"]), label=vista["default_label"])
        resto.setIsElse(True)
        raiz.appendChild(resto)
        return QgsRuleBasedRenderer(raiz), avisos

    if tipo == "rule_based":
        raiz = QgsRuleBasedRenderer.Rule(None)
        anteriores = []
        for etiqueta, expresion, color in vista["rules"]:
            # Gana la primera regla que case, como en el frontal.
            filtro = expresion
            if anteriores:
                filtro = f"{expresion} AND NOT ({' OR '.join(anteriores)})"
            raiz.appendChild(
                QgsRuleBasedRenderer.Rule(fabrica(color), filterExp=filtro, label=etiqueta)
            )
            anteriores.append(expresion)
        resto = QgsRuleBasedRenderer.Rule(fabrica(vista["default"]), label="Otros")
        resto.setIsElse(True)
        raiz.appendChild(resto)
        return QgsRuleBasedRenderer(raiz), avisos

    if tipo == "hexagon":
        # Los hexágonos los pinta una capa de teselas del servidor; si se llega
        # aquí es que no se pudo montar, y quedan los puntos.
        avisos.append(
            "Los hexágonos se piden al servidor y no se pudo: se pintan los puntos."
        )
        color = styles.ramp_colors(vista["ramp"], 6)[3]
        return QgsSingleSymbolRenderer(make_symbol(familia, color)), avisos

    if tipo == "heatmap":
        calor = QgsHeatmapRenderer()
        calor.setRadius(vista["radius"])
        calor.setRadiusUnit(QgsUnitTypes.RenderPixels)
        calor.setColorRamp(heatmap_ramp(vista))
        if hasattr(calor, "setLegendSettings"):  # no en QGIS 3.34: «Mínimo» y «Máximo»
            leyenda = QgsColorRampLegendNodeSettings()
            leyenda.setMinimumLabel("Baja densidad")
            leyenda.setMaximumLabel("Alta densidad")
            calor.setLegendSettings(leyenda)
        if vista["weight"]:
            campo = resolver(vista["weight"])
            if campo:
                calor.setWeightExpression(f"to_real({S._quote_field(campo)})")
        return calor, avisos

    return QgsSingleSymbolRenderer(make_symbol(familia, styles.FALLBACK_ANY)), avisos


def _rampa_continua(valor, paradas, minimo, maximo, alfa=styles.DEFAULT_ALPHA):
    """Expresión de color de ``getColorFromRamp`` de la web: la posición del valor entre
    ``minimo`` y ``maximo``, recortada a [0, 1], interpolando entre las paradas de la
    rampa y redondeando como ``Math.round``."""
    ultimo = len(paradas) - 1
    if ultimo == 0 or maximo == minimo:
        return "color_rgba({}, {}, {}, {})".format(*paradas[0], alfa)
    t = f"max(0, min(1, ({valor} - {S._number(minimo)}) / {S._number(maximo - minimo)}))"
    tramos = []
    for k in range(ultimo):
        a, b = paradas[k], paradas[k + 1]
        canales = ", ".join(f"floor({a[i]} + (@p - {k}) * {b[i] - a[i]} + 0.5)" for i in range(3))
        tramos.append(f"WHEN @p < {k + 1} THEN color_rgba({canales}, {alfa})")
    final = "color_rgba({}, {}, {}, {})".format(*paradas[-1], alfa)
    return f"with_variable('p', {t} * {ultimo}, CASE {' '.join(tramos)} ELSE {final} END)"


def _color_calculado(simbolo, familia, expresion):
    """Pone ``expresion`` de color al símbolo, y su borde oscurecido como ``stroke_of``."""
    borde = (
        f"with_variable('c', {expresion}, color_rgba("
        + ", ".join(f"floor(color_part(@c, '{p}') * {styles.STROKE_FACTOR})" for p in ("red", "green", "blue"))
        + ", color_part(@c, 'alpha')))"
    )
    capa = simbolo.symbolLayer(0)
    if familia != "line":
        capa.setDataDefinedProperty(QgsSymbolLayer.PropertyFillColor, QgsProperty.fromExpression(expresion))
    capa.setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeColor, QgsProperty.fromExpression(borde))


def heatmap_ramp(vista):
    """La rampa del calor como la pinta el ``HeatmapLayer`` de la web.

    Su sombreador (deck.gl 9, ``triangle-layer-fragment``), con ``v`` el peso entre el
    máximo: el color sale de una textura de los seis colores con filtro lineal en
    ``f = min(v · intensity, 1)``, con los centros de los píxeles en ``(i + 0,5)/6``; la
    opacidad es ``min(v · intensity / threshold, 1)``. Por debajo del umbral se ve el
    primer color, cada vez más transparente (con ``inferno``, el borde negro). Color y
    opacidad son lineales a trozos, así que basta una parada en cada quiebro.
    """
    colores = [c[:3] for c in styles.ramp_colors(vista["ramp"], 6)]
    intensidad = max(float(vista.get("intensity", 1) or 1), 1e-6)
    umbral = max(float(vista.get("threshold", 0.05) or 0.05), 1e-6)

    def color_en(v):
        f = min(v * intensidad, 1.0)
        x = f * len(colores) - 0.5
        if x <= 0:
            rgb = colores[0]
        elif x >= len(colores) - 1:
            rgb = colores[-1]
        else:
            i = math.floor(x)
            k = x - i
            rgb = tuple(round(a + (b - a) * k) for a, b in zip(colores[i], colores[i + 1]))
        alfa = round(255 * min(v * intensidad / umbral, 1.0))
        return QColor(*rgb, alfa)

    quiebros = {umbral / intensidad} | {(i + 0.5) / (len(colores) * intensidad) for i in range(len(colores))}
    paradas = [QgsGradientStop(v, color_en(v)) for v in sorted(q for q in quiebros if 0 < q < 1)]
    return QgsGradientColorRamp(color_en(0.0), color_en(1.0), False, paradas)


def hexagon_renderer(vista):
    """Las celdas de las teselas agregadas, coloreadas por su número de puntos."""
    from . import aggregated

    rampa = [color[:3] + (200,) for color in styles.ramp_colors(vista["ramp"], 6)]
    tramo = aggregated.count_bucket_expression(vista["color_max"])
    estilos = []
    # Un estilo por tramo de la rampa: la leyenda de QGIS sale como el degradado de
    # la web, con «Baja densidad» y «Alta densidad» en los extremos.
    for i, ((r, g, b, a), etiqueta) in enumerate(zip(rampa, aggregated.LEYENDA)):
        relleno = QgsFillSymbol.createSimple({"color": f"{r},{g},{b},{a}", "outline_style": "no"})
        estilo = QgsVectorTileBasicRendererStyle(etiqueta, aggregated.CAPA_MVT, Qgis.GeometryType.Polygon)
        estilo.setFilterExpression(f"{tramo} = {i}")
        estilo.setSymbol(relleno)
        estilos.append(estilo)
    renderizador = QgsVectorTileBasicRenderer()
    renderizador.setStyles(estilos)
    return renderizador


def cells_renderer(vista):
    """Las celdas agregadas de una capa de polígonos (``gui/celdas.py``): un color por
    tramo de ``count``, como ``countColor`` de la web (rampa de seis, alfa 200)."""
    from . import aggregated

    rampa = [color[:3] + (200,) for color in styles.ramp_colors(vista["ramp"], 6)]
    tramo = aggregated.count_bucket_expression(vista["color_max"])
    raiz = QgsRuleBasedRenderer.Rule(None)
    for i, ((r, g, b, a), etiqueta) in enumerate(zip(rampa, aggregated.LEYENDA)):
        relleno = QgsFillSymbol.createSimple({"color": f"{r},{g},{b},{a}", "outline_style": "no"})
        raiz.appendChild(QgsRuleBasedRenderer.Rule(relleno, filterExp=f"{tramo} = {i}", label=etiqueta))
    return QgsRuleBasedRenderer(raiz)


def apply_labels(layer, campo, geometry_type):
    """Etiquetas como las de la web: texto oscuro con halo blanco, de cerca."""
    formato = QgsTextFormat()
    formato.setSize(8)
    formato.setColor(QColor(25, 25, 25))
    halo = QgsTextBufferSettings()
    halo.setEnabled(True)
    halo.setSize(1)
    halo.setColor(QColor(255, 255, 255))
    formato.setBuffer(halo)

    ajustes = QgsPalLayerSettings()
    ajustes.fieldName = campo
    ajustes.setFormat(formato)
    ajustes.scaleVisibility = True
    ajustes.maximumScale = 0
    ajustes.minimumScale = styles.LABEL_MAX_SCALE
    if styles.geometry_family(geometry_type) == "point":
        # Debajo del punto, como en las teselas del frontal.
        ajustes.placement = Qgis.LabelPlacement.OverPoint
        ajustes.quadOffset = Qgis.LabelQuadrantPosition.Below
        ajustes.yOffset = 2
    layer.setLabeling(QgsVectorLayerSimpleLabeling(ajustes))
    layer.setLabelsEnabled(True)
