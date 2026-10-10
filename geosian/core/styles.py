"""Simbología de Geosian, sin QGIS delante.

Reproduce cómo pinta la plataforma cada elemento para que en QGIS se vea igual.
Hay dos fuentes:

- El estilo base de la capa, en ``schema.styles`` del LAD. Es el que usa
  ``getFeatureColor`` del frontal (``layerUtils.js``): reglas de color por valor
  de atributo, con prioridad, un color por defecto y un estilo por geometría
  para lo que no case con nada.
- El ``style_config`` de una vista de capa, que puede ser de color único,
  categorizado, graduado, por reglas o un mapa de calor.

Aquí solo se calcula *qué* color lleva cada caso. El módulo ``symbology``
convierte el resultado en renderizadores de QGIS.

Los colores van siempre como tuplas ``(r, g, b, a)`` de 0 a 255.
"""

from . import schema as S

# Alfa que pone el frontal cuando el color no lo trae (``hexToRgba``).
DEFAULT_ALPHA = 230

# Lo que pinta el frontal si el LAD no dice nada (``layerConstants.js``).
FALLBACK_POINT = (242, 112, 19, DEFAULT_ALPHA)
FALLBACK_MULTIPOINT = (76, 175, 80, DEFAULT_ALPHA)
FALLBACK_LINE = (33, 150, 243, DEFAULT_ALPHA)
FALLBACK_POLYGON = (238, 130, 238)
FALLBACK_ANY = (128, 128, 128, DEFAULT_ALPHA)
FALLBACK_VIEW = (158, 158, 158, DEFAULT_ALPHA)

# Las líneas, los contornos y los bordes de los puntos van un 40 % más oscuros
# que el relleno, como en las teselas del frontal.
STROKE_FACTOR = 0.6

_FAMILIA = {
    "points": "point",
    "multi_points": "point",
    "lines": "line",
    "multi_lines": "line",
    "polygons": "polygon",
    "multi_polygons": "polygon",
}


def geometry_family(geometry_type):
    """``point``, ``line`` o ``polygon`` para un tipo de la URI."""
    return _FAMILIA.get(geometry_type or "", "point")


def hex_to_rgba(valor, alpha=DEFAULT_ALPHA):
    """``#RRGGBB`` o ``#RRGGBBAA`` a tupla. Lo demás, negro opaco.

    Es exactamente lo que hace ``hexToRgba`` en el frontal, incluido el negro
    para los formatos que no entiende: así un color mal escrito se ve igual de
    mal en los dos sitios y se corrige en el LAD, no aquí.
    """
    texto = str(valor or "").strip().removeprefix("#")
    try:
        if len(texto) == 6:
            return (int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16), alpha)
        if len(texto) == 8:
            return (
                int(texto[0:2], 16),
                int(texto[2:4], 16),
                int(texto[4:6], 16),
                int(texto[6:8], 16),
            )
    except ValueError:
        pass
    return (0, 0, 0, 255)


def color_from_any(valor, alpha=DEFAULT_ALPHA):
    """Color de un ``style_config``: lista ``[r, g, b(, a)]`` o hex."""
    if isinstance(valor, (list, tuple)) and len(valor) >= 3:
        try:
            r, g, b = (round(float(c)) for c in valor[:3])
            a = round(float(valor[3])) if len(valor) > 3 else alpha
            return (r, g, b, a)
        except (TypeError, ValueError):
            return None
    if isinstance(valor, str):
        return hex_to_rgba(valor, alpha)
    return None


def stroke_of(color):
    """El color de línea que acompaña a un relleno."""
    r, g, b, a = color
    return (int(r * STROKE_FACTOR), int(g * STROKE_FACTOR), int(b * STROKE_FACTOR), a)


def value_key(valor):
    """Cómo compara el frontal un valor con las claves de ``allowed_values``."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


# ----------------------------------------------------------------------
# Estilo base (LAD)
# ----------------------------------------------------------------------


def geometry_default(schema, geometry_type):
    """Color por geometría (``getGeometryStyleColors``) cuando no hay reglas."""
    geometrias = ((schema or {}).get("styles") or {}).get("geometries") or {}
    familia = geometry_family(geometry_type)

    if familia == "point":
        estilo = geometrias.get("pointStyle") or {}
        if estilo.get("fill-color"):
            return hex_to_rgba(estilo["fill-color"])
        if geometry_type == "multi_points":
            return FALLBACK_MULTIPOINT
        return FALLBACK_POINT

    if familia == "line":
        estilo = geometrias.get("lineStyle") or {}
        if estilo.get("color"):
            return hex_to_rgba(estilo["color"])
        return FALLBACK_LINE

    estilo = geometrias.get("polyStyle") or {}
    try:
        opacidad = float(estilo.get("fill-opacity", 0.5))
    except (TypeError, ValueError):
        opacidad = 0.5
    alfa = round(255 * opacidad)
    if estilo.get("fill-color"):
        r, g, b, _ = hex_to_rgba(estilo["fill-color"])
        return (r, g, b, alfa)
    return FALLBACK_POLYGON + (alfa,)


def base_style(schema, geometry_type):
    """Reglas de color del estilo base de una capa.

    Returns:
        ``{"rules": [...], "default": color, "default_label": str}``. Cada
        regla es ``{"attribute", "value", "color", "label", "excluded"}``, en
        el orden en que se evalúan. ``excluded`` son los atributos y valores de
        las reglas de más prioridad: un elemento solo cae en esta regla si no
        cayó antes en una de esas, que es lo que hace el frontal al quedarse
        con la regla de menor ``priority`` que case.
    """
    estilos = (schema or {}).get("styles") or {}
    reglas_lad = [
        r
        for r in (estilos.get("colors") or [])
        if isinstance(r, dict) and r.get("attribute")
    ]
    # Orden estable por prioridad: sin prioridad cuenta como 999.
    reglas_lad = sorted(reglas_lad, key=lambda r: _priority(r.get("priority")))

    reglas = []
    anteriores = []
    for regla in reglas_lad:
        atributo = str(regla["attribute"])
        valores = regla.get("allowed_values") or {}
        if not isinstance(valores, dict):
            continue
        claves = []
        for valor, color in valores.items():
            reglas.append(
                {
                    "attribute": atributo,
                    "value": str(valor),
                    "color": hex_to_rgba(color),
                    "label": str(valor),
                    "excluded": list(anteriores),
                }
            )
            claves.append(str(valor))
        if claves:
            anteriores.append((atributo, claves))

    # Color por defecto: el de la regla de más prioridad que lo tenga. Si
    # ninguna lo tiene, el de la geometría.
    por_defecto = None
    for regla in reglas_lad:
        if regla.get("default"):
            por_defecto = hex_to_rgba(regla["default"])
            break
    if por_defecto is None:
        por_defecto = geometry_default(schema, geometry_type)

    return {
        "rules": reglas,
        "default": por_defecto,
        "default_label": "Otros" if reglas else "",
    }


def _priority(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 999.0


# ----------------------------------------------------------------------
# Estilo de una vista (style_config)
# ----------------------------------------------------------------------


def view_style(style_config, geometry_type, schema=None):
    """Interpreta el ``style_config`` de una vista.

    Returns:
        ``{"kind": ..., ...}`` con ``kind`` uno de:

        - ``single``: ``color``.
        - ``categorized``: ``attribute``, ``categories`` (lista de
          ``(valor, color, etiqueta)``), ``default``, ``default_label``.
        - ``graduated``: ``attribute`` y ``ranges`` (lista de
          ``(desde, hasta, color, etiqueta)``; ``None`` es abierto).
        - ``rule_based``: ``rules`` (lista de ``(etiqueta, expresión, color)``)
          y ``default``.
        - ``heatmap``: ``radius`` (px), ``weight`` (atributo o ``None``) y
          ``ramp`` (nombre).

        Lleva además ``unsupported`` con el nombre de la visualización si no
        tiene equivalente en QGIS y se ha caído al color normal, y
        ``base_fallback`` con el estilo base si el ``style_config`` no da
        color.
    """
    config = style_config if isinstance(style_config, dict) else {}
    color = config.get("color") if isinstance(config.get("color"), dict) else {}
    visualizacion = config.get("visualization") or "default"

    resultado = {"unsupported": None}
    if visualizacion == "heatmap" and geometry_family(geometry_type) == "point":
        calor = config.get("heatmap") or {}
        resultado.update(
            kind="heatmap",
            radius=_number_or(calor.get("radiusPixels"), 30),
            weight=calor.get("weightAttribute") or None,
            ramp=calor.get("colorRamp") or "inferno",
            intensity=max(_number_or(calor.get("intensity"), 1), 0.01),
            threshold=min(max(_number_or(calor.get("threshold"), 0.05), 0.0), 0.99),
            opacity=view_opacity(config),
        )
        return resultado
    if visualizacion in ("hexagon", "h3hexagon") and geometry_family(geometry_type) == "point":
        # Los agrega el servidor en teselas (``core/aggregated.py``), como la web
        # sobre una capa grande: color por número de puntos.
        hexagono = config.get(visualizacion) or {}
        resultado.update(
            kind="hexagon",
            ramp=hexagono.get("colorRamp") or ("plasma" if visualizacion == "h3hexagon" else "viridis"),
            color_max=_number_or(hexagono.get("colorMax"), 100),
            opacity=view_opacity(config),
        )
        return resultado
    if visualizacion not in ("default", "icon"):
        # Contornos: todavía sin equivalente en QGIS. Se pinta el color.
        resultado["unsupported"] = visualizacion

    modo = color.get("mode") or config.get("mode") or "single"

    icono = config.get("icon") if isinstance(config.get("icon"), dict) else {}
    defecto = icono.get("defaultIcon") if isinstance(icono.get("defaultIcon"), dict) else {}
    if visualizacion == "icon" and defecto.get("lib") and defecto.get("name"):
        resultado["icon"] = {
            "lib": str(defecto["lib"]),
            "name": str(defecto["name"]),
            "size": _number_or(icono.get("size"), 24),
            "size_min": _number_or(icono.get("sizeMin"), 16),
        }
        # El color del icono (viewVisualizationHelpers.js): fijo si no va
        # coloreado; el de la vista si es categorizada o graduada; si no, el
        # del estilo de la capa, no el color único de la vista.
        if icono.get("colored") is False:
            resultado.update(
                kind="single",
                color=color_from_any(icono.get("fixedColor")) or (33, 150, 243, DEFAULT_ALPHA),
            )
            return resultado
        if modo not in ("categorized", "graduated"):
            resultado.update(kind="base", base_fallback=base_style(schema, geometry_type))
            return resultado

    if modo == "categorized" and color.get("attribute"):
        categorias = []
        for valor, datos in (color.get("categories") or {}).items():
            datos = datos if isinstance(datos, dict) else {"color": datos}
            c = color_from_any(datos.get("color"))
            if c is None:
                continue
            categorias.append((str(valor), c, str(datos.get("label") or valor)))
        defecto = color.get("default") if isinstance(color.get("default"), dict) else {}
        resultado.update(
            kind="categorized",
            attribute=str(color["attribute"]),
            categories=categorias,
            default=color_from_any(defecto.get("color")) or FALLBACK_VIEW,
            default_label=str(defecto.get("label") or "Otros"),
        )
        return resultado

    if modo == "graduated" and color.get("attribute"):
        resultado.update(
            kind="graduated",
            attribute=str(color["attribute"]),
            ranges=_graduated_ranges(color),
        )
        return resultado

    if modo == "rule_based" and color.get("rules"):
        reglas = []
        for i, regla in enumerate(color.get("rules") or []):
            if not isinstance(regla, dict):
                continue
            expresion = filter_group_expression(regla.get("filter") or {})
            c = color_from_any((regla.get("style") or {}).get("color"))
            if expresion is None or c is None:
                continue
            reglas.append((str(regla.get("name") or f"Regla {i + 1}"), expresion, c))
        otra = color_from_any((color.get("else") or {}).get("color"))
        resultado.update(kind="rule_based", rules=reglas, default=otra)
        return resultado

    unico = color_from_any(color.get("value"))
    if unico is None:
        # Sin color propio la vista se ve con el estilo de la capa.
        resultado.update(kind="base", base_fallback=base_style(schema, geometry_type))
        return resultado
    resultado.update(kind="single", color=unico)
    return resultado


def view_opacity(style_config):
    """La opacidad de una vista: la de sus puntos, como la web (0,9 por omisión)."""
    punto = (style_config or {}).get("point") if isinstance(style_config, dict) else None
    valor = _number_or((punto or {}).get("opacity"), 0.9)
    return min(1.0, max(0.0, valor))


def _graduated_ranges(color):
    cortes = []
    for valor in color.get("breaks") or []:
        try:
            cortes.append(float(valor))
        except (TypeError, ValueError):
            continue
    colores = [c for c in (color_from_any(v) for v in color.get("colors") or []) if c]
    etiquetas = [str(e) for e in (color.get("labels") or [])]
    if not cortes:
        return []
    if not colores:
        colores = ramp_colors(color.get("colorRamp") or "viridis", max(len(cortes), 2))

    # El frontal: [breaks[i], breaks[i+1]) da colors[i]; por debajo del primer
    # corte, el primer color; por encima del último, el último.
    tramos = []
    limites = [None] + cortes + [None]
    for i in range(len(limites) - 1):
        desde, hasta = limites[i], limites[i + 1]
        indice = min(max(i - 1, 0), len(colores) - 1)
        # Las etiquetas del editor son de los tramos entre cortes; el de por
        # debajo del primero no tiene la suya y lleva la automática.
        if desde is not None and indice < len(etiquetas):
            etiqueta = etiquetas[indice]
        else:
            etiqueta = _range_label(desde, hasta)
        tramos.append((desde, hasta, colores[indice], etiqueta))
    return tramos


def _range_label(desde, hasta):
    if desde is None:
        return f"< {hasta:g}"
    if hasta is None:
        return f"≥ {desde:g}"
    return f"{desde:g} – {hasta:g}"


def _number_or(valor, defecto):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return float(defecto)


# Rampas que usa el editor de vistas (``colorRamps.js``), con sus extremos y un
# punto medio. Basta para una aproximación fiel a la vista; los tramos se
# interpolan entre estos puntos.
RAMPS = {
    "viridis": [(68, 1, 84), (33, 145, 140), (253, 231, 37)],
    "inferno": [(0, 0, 4), (187, 55, 84), (252, 255, 164)],
    "plasma": [(13, 8, 135), (204, 71, 120), (240, 249, 33)],
    "magma": [(0, 0, 4), (183, 55, 121), (252, 253, 191)],
    "blues": [(247, 251, 255), (107, 174, 214), (8, 48, 107)],
    "reds": [(255, 245, 240), (251, 106, 74), (103, 0, 13)],
    "greens": [(247, 252, 245), (116, 196, 118), (0, 68, 27)],
}


def ramp_colors(nombre, n):
    puntos = RAMPS.get(str(nombre).lower(), RAMPS["viridis"])
    if n <= 1:
        return [puntos[0] + (DEFAULT_ALPHA,)]
    colores = []
    for i in range(n):
        t = i / (n - 1) * (len(puntos) - 1)
        j = min(int(t), len(puntos) - 2)
        f = t - j
        a, b = puntos[j], puntos[j + 1]
        colores.append(
            tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3)) + (DEFAULT_ALPHA,)
        )
    return colores


# ----------------------------------------------------------------------
# Expresiones de QGIS
# ----------------------------------------------------------------------


def match_expression(campo, valor):
    """``campo`` vale ``valor``, comparando como el frontal: como texto."""
    return f"to_string({S._quote_field(campo)}) = {S._quote_value(str(valor))}"


def filter_group_expression(grupo, campos=None):
    """Un grupo ``{operator, rules}`` de una regla de estilo a expresión.

    ``campos`` traduce nombres de atributo a nombres de campo de QGIS. Las
    reglas con operadores desconocidos se omiten; si no queda ninguna, devuelve
    ``None``.
    """
    operador = " OR " if str(grupo.get("operator", "and")).lower() == "or" else " AND "
    partes = []
    for regla in grupo.get("rules") or []:
        if not isinstance(regla, dict) or not regla.get("field"):
            continue
        campo = (campos or {}).get(regla["field"], regla["field"])
        expresion = _rule_expression(campo, regla.get("operator"), regla.get("value"))
        if expresion:
            partes.append(expresion)
    if not partes:
        return None
    return "(" + operador.join(partes) + ")"


def _rule_expression(campo, operador, valor):
    ref = S._quote_field(campo)
    texto = f"to_string({ref})"
    op = str(operador or "").lower()
    if op in ("equals", "=", "eq"):
        return f"{texto} = {S._quote_value(value_key(valor))}"
    if op in ("not_equals", "!=", "neq"):
        return f"({texto} IS NULL OR {texto} <> {S._quote_value(value_key(valor))})"
    if op in ("in", "not_in"):
        valores = valor if isinstance(valor, list) else [valor]
        lista = ", ".join(S._quote_value(value_key(v)) for v in valores)
        if not lista:
            return None
        return f"{texto} IN ({lista})" if op == "in" else f"{texto} NOT IN ({lista})"
    numericos = {
        ">": ">", "gt": ">", "greater_than": ">",
        ">=": ">=", "gte": ">=", "greater_or_equal": ">=",
        "<": "<", "lt": "<", "less_than": "<",
        "<=": "<=", "lte": "<=", "less_or_equal": "<=",
    }
    if op in numericos:
        return f"to_real({ref}) {numericos[op]} {S._number(valor)}"
    if op == "between" and isinstance(valor, list) and len(valor) == 2:
        return f"to_real({ref}) BETWEEN {S._number(valor[0])} AND {S._number(valor[1])}"
    texto_minus = f"lower({texto})"
    patron = str(valor or "").lower().replace("'", "''").replace("%", "\\%")
    if op == "contains":
        return f"{texto_minus} LIKE '%{patron}%'"
    if op == "not_contains":
        return f"({texto} IS NULL OR {texto_minus} NOT LIKE '%{patron}%')"
    if op == "starts_with":
        return f"{texto_minus} LIKE '{patron}%'"
    if op == "ends_with":
        return f"{texto_minus} LIKE '%{patron}'"
    if op in ("is_null", "is_empty"):
        return f"({ref} IS NULL OR {texto} = '')"
    if op in ("is_not_null", "is_not_empty"):
        return f"({ref} IS NOT NULL AND {texto} <> '')"
    return None


# ----------------------------------------------------------------------
# Etiquetas
# ----------------------------------------------------------------------

# La web solo pinta etiquetas con zoom 15 o más; en escala, unos 1:17.000.
LABEL_MAX_SCALE = 17000


def label_choices(schema):
    """Atributos que la web deja poner de etiqueta: ``(nombre, título)``.

    ``LabelSelector.jsx`` ofrece los que declaran ``label`` en el esquema, a
    ``true`` o a ``false``: el valor solo dice si se enciende solo.
    """
    return [
        (str(attr["name"]), S.field_title(attr))
        for attr in S.flatten_attributes(schema or {})
        if "label" in attr and attr.get("name")
    ]


def label_attribute(schema):
    """Atributo que la web etiqueta por defecto, o ``None``.

    Las etiquetas no se guardan en ningún sitio: son estado de la sesión del
    navegador. Lo que sí está en el esquema es cuáles se encienden solas
    (``LabelSelector.jsx``): un atributo con ``label: true`` que además está en
    ``attributes_on_map`` o colorea la capa en ``styles.colors``. Se devuelve
    el primero, porque la web etiqueta un atributo por capa.
    """
    esquema = schema or {}
    en_mapa = {str(a) for a in esquema.get("attributes_on_map") or []}
    for regla in ((esquema.get("styles") or {}).get("colors") or []):
        if isinstance(regla, dict) and regla.get("attribute"):
            en_mapa.add(str(regla["attribute"]))

    for attr in S.flatten_attributes(esquema):
        etiqueta = attr.get("label")
        if etiqueta is True or str(etiqueta).lower() == "true":
            nombre = str(attr.get("name") or "")
            if nombre and (nombre in en_mapa or any(p.split(".")[-1] == nombre for p in en_mapa)):
                return nombre
    return None
