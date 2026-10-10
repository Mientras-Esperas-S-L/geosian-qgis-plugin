"""Lectura del esquema de atributos de Geosian (LAD).

Aquí vive todo lo que se puede razonar sin QGIS delante: aplanar las secciones
anidadas, clasificar los tipos y traducir las condiciones de visibilidad al
lenguaje de expresiones de QGIS. El módulo ``lad`` es el que convierte esto en
campos y formularios de verdad.

Tipos que usa Geosian, sacados del catálogo real de esquemas en producción:

    contenedores : section, page_section, section_decision
    texto        : string, text
    números      : integer, number
    elección     : select, radio, autocomplete, checkbox
    fecha        : calendar
    adjuntos     : images, files
"""

CONTAINER_TYPES = {"section", "page_section", "section_decision"}
ATTACHMENT_TYPES = {"images", "files"}
TEXT_TYPES = {"string", "text"}
NUMERIC_TYPES = {"integer", "number"}
CHOICE_TYPES = {"select", "radio", "autocomplete", "checkbox"}
DATE_TYPES = {"calendar"}

# Nombres que el proveedor reserva para sus propios campos. Un atributo del LAD
# que se llame igual se renombra con el prefijo, que es la misma convención que
# ya usa la plataforma para las colisiones de nombres reservados.
RESERVED_NAMES = {"id", "geometry", "geom"}
RESERVED_PREFIX = "attr__"


def flatten_attributes(schema):
    """Devuelve los atributos de hoja del esquema, en orden y sin secciones.

    Las secciones pueden anidarse unas dentro de otras, así que se recorre en
    profundidad. Cada atributo devuelto lleva ``_path``, la lista de secciones
    que lo contienen, que es lo que luego reconstruye las pestañas del
    formulario.

    Args:
        schema: el ``schema`` de una definición de atributos, o su lista de
            ``attributes`` directamente.

    Returns:
        Lista de diccionarios de atributo, cada uno con ``_path`` añadido.
    """
    if isinstance(schema, dict):
        atributos = schema.get("attributes") or []
    else:
        atributos = schema or []

    salida = []
    _walk(atributos, (), salida)
    return salida


def merged_attributes(schema):
    """Como ``flatten_attributes``, pero un atributo por nombre.

    Un mismo dato puede definirse en varias ramas del formulario (en el arbolado de Cáceres,
    «Especie» en la de árboles y en la de palmeras, cada una con su lista): la web enseña la
    que toca, pero es un solo dato y en QGIS un solo campo. Se queda la primera definición, con
    los valores permitidos de todas, en orden y sin repetir.
    """
    salida, por_nombre = [], {}
    for attr in flatten_attributes(schema):
        nombre = attr.get("name")
        if not nombre or nombre not in por_nombre:
            copia = dict(attr)
            salida.append(copia)
            if nombre:
                por_nombre[nombre] = copia
            continue
        primero = por_nombre[nombre]
        valores = allowed_values(primero)
        nuevos = [v for v in allowed_values(attr) if v not in valores]
        if nuevos:
            primero["allowed_values"] = valores + nuevos
    return salida


def _walk(atributos, path, salida):
    for attr in atributos:
        if not isinstance(attr, dict):
            continue
        if attr.get("type") in CONTAINER_TYPES:
            hijos = attr.get("contents") or []
            _walk(hijos, path + (attr,), salida)
        else:
            copia = dict(attr)
            copia["_path"] = list(path)
            salida.append(copia)


def iter_containers(schema):
    """Recorre el esquema devolviendo ``(contenedor, hijos)`` de cada sección."""
    if isinstance(schema, dict):
        atributos = schema.get("attributes") or []
    else:
        atributos = schema or []
    for attr in atributos:
        if isinstance(attr, dict) and attr.get("type") in CONTAINER_TYPES:
            yield attr, attr.get("contents") or []


def is_attachment(attr):
    return attr.get("type") in ATTACHMENT_TYPES


def is_multiple(attr):
    """Si el atributo guarda una lista de valores en vez de uno solo.

    ``checkbox`` con ``allowed_values`` es de suyo una lista aunque no venga
    marcado como múltiple: es una casilla por valor permitido.
    """
    if attr.get("multiple"):
        return True
    return attr.get("type") == "checkbox" and bool(attr.get("allowed_values"))


def is_boolean(attr):
    """Casilla suelta, sin lista de valores: un sí o no."""
    return attr.get("type") == "checkbox" and not attr.get("allowed_values")


def allowed_values(attr):
    """Valores permitidos, ya resueltos.

    La API resuelve los ``allowed_values`` dinámicos antes de servir el
    esquema, así que aquí solo llegan listas. Si aun así llega la forma con
    ``depends_on``, se devuelve vacío en vez de romper: el campo se queda como
    texto libre, que es preferible a no poder abrir la capa.
    """
    valores = attr.get("allowed_values")
    if isinstance(valores, list):
        return [v for v in valores if v is not None]
    return []


def field_name(attr, usados=None):
    """Nombre de campo para QGIS, esquivando los nombres reservados."""
    nombre = attr.get("name") or ""
    if nombre in RESERVED_NAMES:
        nombre = RESERVED_PREFIX + nombre
    if usados is not None:
        base = nombre
        n = 2
        while nombre in usados:
            nombre = f"{base}_{n}"
            n += 1
        usados.add(nombre)
    return nombre


def field_title(attr):
    return attr.get("title") or attr.get("name") or ""


def is_editable(attr):
    return attr.get("editable", True) is not False


def is_visible(attr):
    return attr.get("visible", True) is not False


def is_required(attr):
    return bool(attr.get("required"))


# ----------------------------------------------------------------------
# Visibilidad condicional
# ----------------------------------------------------------------------

def visible_if_to_expression(condition):
    """Traduce un ``visible_if`` a una expresión de QGIS.

    Los once operadores son los que implementa ``evaluateVisibilityCondition``
    en el frontend, y la traducción respeta su semántica **incluida una
    peculiaridad**: si el campo del que se depende está vacío, el frontend
    oculta el campo sea cual sea el operador, y lo hace antes de mirarlo. Eso
    significa que ``is_empty`` en la web nunca llega a ser cierto. Aquí se
    replica a propósito, porque el técnico tiene que ver el mismo formulario en
    QGIS y en el navegador; si algún día se corrige en el frontend, hay que
    corregirlo también aquí.

    Returns:
        La expresión, o ``None`` si la condición no es traducible (en cuyo caso
        el campo se deja visible, que es el fallo seguro).
    """
    if not isinstance(condition, dict):
        return None

    campo = condition.get("field")
    operador = condition.get("operator")
    valor = condition.get("value")
    valores = condition.get("values")

    if not campo or not operador:
        return None

    ref = _quote_field(campo)
    # El "tiene valor" que el frontend exige antes de evaluar nada. En QGIS,
    # to_string de una lista da NULL: si es lista, cuenta su longitud.
    tiene_valor = (
        f"({ref} IS NOT NULL AND "
        f"coalesce(try(array_length({ref}) > 0, NULL), to_string({ref}) <> ''))"
    )

    expr = _operator_expression(ref, operador, valor, valores)
    if expr is None:
        return None
    return f"({tiene_valor} AND ({expr}))"


def _operator_expression(ref, operador, valor, valores):
    if operador == "equals":
        return f"({_contains(ref, valor)} OR coalesce({ref} = {_quote_value(valor)}, FALSE))"

    if operador == "not_equals":
        # Con una lista, «<>» da NULL: manda la pertenencia.
        return f"(NOT {_contains(ref, valor)} AND coalesce({ref} <> {_quote_value(valor)}, TRUE))"

    if operador == "contains":
        # Vale para lista (contiene el elemento) y para texto (subcadena).
        return (
            f"({_contains(ref, valor)} OR "
            f"to_string({ref}) LIKE {_quote_value('%' + str(valor) + '%')})"
        )

    if operador == "contains_any":
        if not isinstance(valores, list) or not valores:
            return "FALSE"
        partes = [_contains(ref, v) for v in valores]
        lista = ", ".join(_quote_value(v) for v in valores)
        return "(" + " OR ".join(partes) + f" OR coalesce({ref} IN ({lista}), FALSE))"

    if operador == "contains_all":
        if not isinstance(valores, list) or not valores:
            return "FALSE"
        return "(" + " AND ".join(_contains(ref, v) for v in valores) + ")"

    if operador == "is_empty":
        # Inalcanzable por la guarda de "tiene valor", igual que en el frontend.
        return "FALSE"

    if operador == "is_not_empty":
        return "TRUE"

    if operador in ("greater_than", "less_than", "greater_or_equal", "less_or_equal"):
        simbolo = {
            "greater_than": ">",
            "less_than": "<",
            "greater_or_equal": ">=",
            "less_or_equal": "<=",
        }[operador]
        return f"to_real({ref}) {simbolo} {_number(valor)}"

    return None


def _contains(ref, valor):
    """Comprobación de pertenencia que no revienta si el campo no es lista.

    QGIS no tiene ``is_array``: una expresión que lo use no compila y deja oculto
    lo que dependa de ella. ``array_contains`` sobre un texto da error de
    evaluación, y ``try`` lo convierte en FALSE.
    """
    return f"coalesce(try(array_contains({ref}, {_quote_value(valor)}), FALSE), FALSE)"


def _quote_field(nombre):
    return '"' + str(nombre).replace('"', '""') + '"'


def _quote_value(valor):
    if valor is None:
        return "NULL"
    if isinstance(valor, bool):
        return "TRUE" if valor else "FALSE"
    if isinstance(valor, (int, float)):
        return repr(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def _number(valor):
    try:
        return repr(float(valor))
    except (TypeError, ValueError):
        return "NULL"
