"""Renderizadores de QGIS a partir de la simbología de Geosian.

``styles`` decide qué color lleva cada caso; aquí se monta el renderizador que
lo pinta. Los tamaños imitan a las teselas del frontal: puntos de 12 px con
borde de 1 px, líneas de 2 px y contornos de 1 px, todo en píxeles para que se
vea igual a cualquier escala.
"""

from qgis.core import (
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGraduatedSymbolRenderer,
    QgsHeatmapRenderer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsRendererRange,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
    QgsUnitTypes,
)
from qgis.PyQt.QtGui import QColor

from . import schema as S
from . import styles

POINT_SIZE_PX = 12
LINE_WIDTH_PX = 2
OUTLINE_WIDTH_PX = 1


def _rgba(color):
    return ",".join(str(int(c)) for c in color)


def make_symbol(familia, color):
    """Símbolo de QGIS para un color de relleno de Geosian."""
    borde = styles.stroke_of(color)
    if familia == "point":
        return QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": _rgba(color),
                "outline_color": _rgba(borde),
                "size": str(POINT_SIZE_PX),
                "size_unit": "Pixel",
                "outline_width": str(OUTLINE_WIDTH_PX),
                "outline_width_unit": "Pixel",
            }
        )
    if familia == "line":
        # En las teselas del frontal la línea va con el color oscurecido.
        return QgsLineSymbol.createSimple(
            {
                "line_color": _rgba(borde),
                "line_width": str(LINE_WIDTH_PX),
                "line_width_unit": "Pixel",
            }
        )
    return QgsFillSymbol.createSimple(
        {
            "color": _rgba(color),
            "outline_color": _rgba(borde),
            "outline_width": str(OUTLINE_WIDTH_PX),
            "outline_width_unit": "Pixel",
        }
    )


def field_resolver(fields, attr_map):
    """Traduce un nombre de atributo del LAD al nombre de campo en la capa.

    Admite las rutas con puntos del frontal (``seccion.campo``) quedándose con
    el último tramo. Devuelve ``None`` si la capa no tiene ese campo, por
    ejemplo un atributo de información adicional.
    """
    por_atributo = {}
    for nombre, attr in (attr_map or {}).items():
        if isinstance(attr, dict) and attr.get("name"):
            por_atributo.setdefault(str(attr["name"]), nombre)
    nombres = {fields.at(i).name() for i in range(fields.count())}

    def resolver(atributo):
        atributo = str(atributo or "")
        for candidato in (atributo, atributo.split(".")[-1]):
            if candidato in por_atributo:
                return por_atributo[candidato]
            if candidato in nombres:
                return candidato
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


def _rules_renderer(familia, estilo, resolver):
    avisos = []
    if not estilo["rules"]:
        return QgsSingleSymbolRenderer(make_symbol(familia, estilo["default"])), avisos

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
            make_symbol(familia, regla["color"]),
            filterExp=" AND ".join(partes),
            label=regla["label"],
        )
        raiz.appendChild(hijo)

    resto = QgsRuleBasedRenderer.Rule(
        make_symbol(familia, estilo["default"]), label=estilo["default_label"] or "Otros"
    )
    resto.setIsElse(True)
    raiz.appendChild(resto)

    for atributo in sorted(sin_campo):
        avisos.append(f"La regla de color sobre «{atributo}» no se aplica: la capa no tiene ese campo.")
    return QgsRuleBasedRenderer(raiz), avisos


def view_renderer(style_config, geometry_type, schema, resolver):
    """Renderizador del ``style_config`` de una vista.

    Returns:
        ``(renderizador, avisos)``.
    """
    familia = styles.geometry_family(geometry_type)
    vista = styles.view_style(style_config, geometry_type, schema)
    avisos = []
    if vista.get("unsupported"):
        avisos.append(
            f"La visualización «{vista['unsupported']}» de la vista no existe en QGIS; "
            "se pinta con sus colores."
        )

    tipo = vista["kind"]
    if tipo == "base":
        renderizador, mas = _rules_renderer(familia, vista["base_fallback"], resolver)
        return renderizador, avisos + mas

    if tipo == "single":
        return QgsSingleSymbolRenderer(make_symbol(familia, vista["color"])), avisos

    if tipo == "categorized":
        campo = resolver(vista["attribute"])
        if campo is None:
            avisos.append(
                f"La vista colorea por «{vista['attribute']}», que la capa no tiene; "
                "se pinta con el color por defecto."
            )
            return QgsSingleSymbolRenderer(make_symbol(familia, vista["default"])), avisos
        estilo = {
            "rules": [
                {"attribute": vista["attribute"], "value": v, "color": c, "label": e, "excluded": []}
                for v, c, e in vista["categories"]
            ],
            "default": vista["default"],
            "default_label": vista["default_label"],
        }
        renderizador, mas = _rules_renderer(familia, estilo, resolver)
        return renderizador, avisos + mas

    if tipo == "graduated":
        campo = resolver(vista["attribute"])
        if campo is None or not vista["ranges"]:
            avisos.append(f"La vista gradúa por «{vista['attribute']}», que la capa no tiene.")
            return QgsSingleSymbolRenderer(make_symbol(familia, styles.FALLBACK_VIEW)), avisos
        tramos = []
        for desde, hasta, color, etiqueta in vista["ranges"]:
            tramos.append(
                QgsRendererRange(
                    -1e300 if desde is None else desde,
                    1e300 if hasta is None else hasta,
                    make_symbol(familia, color),
                    etiqueta,
                )
            )
        return QgsGraduatedSymbolRenderer(f"to_real({S._quote_field(campo)})", tramos), avisos

    if tipo == "rule_based":
        raiz = QgsRuleBasedRenderer.Rule(None)
        anteriores = []
        for etiqueta, expresion, color in vista["rules"]:
            # Gana la primera regla que case, como en el frontal.
            filtro = expresion
            if anteriores:
                filtro = f"{expresion} AND NOT ({' OR '.join(anteriores)})"
            raiz.appendChild(
                QgsRuleBasedRenderer.Rule(make_symbol(familia, color), filterExp=filtro, label=etiqueta)
            )
            anteriores.append(expresion)
        if vista["default"] is not None:
            resto = QgsRuleBasedRenderer.Rule(make_symbol(familia, vista["default"]), label="Otros")
            resto.setIsElse(True)
            raiz.appendChild(resto)
        return QgsRuleBasedRenderer(raiz), avisos

    if tipo == "heatmap":
        calor = QgsHeatmapRenderer()
        calor.setRadius(vista["radius"])
        calor.setRadiusUnit(QgsUnitTypes.RenderPixels)
        colores = styles.ramp_colors(vista["ramp"], 2)
        rampa = QgsGradientColorRamp(QColor(*colores[0][:3], 0), QColor(*colores[-1][:3]))
        calor.setColorRamp(rampa)
        if vista["weight"]:
            campo = resolver(vista["weight"])
            if campo:
                calor.setWeightExpression(f"to_real({S._quote_field(campo)})")
        return calor, avisos

    return QgsSingleSymbolRenderer(make_symbol(familia, styles.FALLBACK_ANY)), avisos
