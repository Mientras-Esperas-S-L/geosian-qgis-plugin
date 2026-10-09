"""Del esquema de Geosian a los campos y formularios de QGIS.

Traduce una definición de atributos (LAD) en tres cosas:

1. Los campos de la capa (``QgsFields``), con su tipo.
2. La configuración de edición: alias, listas de valores, obligatoriedad, campos
   de solo lectura.
3. El formulario, con sus pestañas y la visibilidad condicional.

Lo que no se puede traducir se deja en el estado más permisivo, nunca en el que
impide trabajar: un campo que no sabemos restringir queda como texto libre, y una
condición de visibilidad que no sabemos traducir deja el campo visible.
"""

from qgis.core import (
    Qgis,
    QgsAttributeEditorContainer,
    QgsAttributeEditorField,
    QgsAttributeEditorRelation,
    QgsDefaultValue,
    QgsEditFormConfig,
    QgsEditorWidgetSetup,
    QgsField,
    QgsFieldConstraints,
    QgsFields,
    QgsOptionalExpression,
    QgsExpression,
)
from qgis.PyQt.QtCore import QVariant

from . import schema as S

# Campos que el proveedor añade siempre, vengan o no en el esquema.
# ``updated_at`` no se enseña por gusto: es la marca que usará el bloqueo
# optimista de la fase 2 para detectar que alguien tocó el elemento.
SYSTEM_FIELDS = (
    ("id", QVariant.LongLong, "ID interno"),
    ("object_id", QVariant.String, "ID"),
    ("updated_at", QVariant.String, "Última modificación"),
)


def build_fields(schema):
    """Construye los campos de QGIS a partir del esquema.

    Returns:
        Tupla ``(QgsFields, mapa)`` donde ``mapa`` relaciona el nombre del campo
        con su atributo del esquema, para no tener que volver a buscarlo.
    """
    fields = QgsFields()
    mapa = {}
    usados = set()

    definidos = {
        a.get("name") for a in S.flatten_attributes(schema) if isinstance(a, dict)
    }
    for nombre, tipo, alias in SYSTEM_FIELDS:
        # Si el esquema ya define el campo, manda el esquema: es el mismo dato
        # con mejor título. Salvo que sea un nombre reservado, porque entonces
        # el atributo del esquema se renombra y el de sistema sigue haciendo
        # falta (si no, la capa se quedaría sin identificador).
        if nombre in definidos and nombre not in S.RESERVED_NAMES:
            continue
        campo = QgsField(nombre, tipo, _type_name(tipo))
        campo.setAlias(alias)
        fields.append(campo)
        usados.add(nombre)

    _append_schema_fields(fields, mapa, usados, schema)
    return fields, mapa


# Los de un parte (información adicional): el suyo, el del elemento al que
# pertenece, que es por donde se relaciona con su capa, y quién y cuándo.
INFO_SYSTEM_FIELDS = (
    ("id", QVariant.LongLong, "ID del parte"),
    ("geodata_id", QVariant.LongLong, "ID interno del elemento"),
    ("usuario", QVariant.String, "Usuario"),
    ("created_at", QVariant.String, "Fecha"),
    ("updated_at", QVariant.String, "Última modificación"),
)


def build_info_fields(info_schema):
    """Como :func:`build_fields`, para un tipo de información adicional."""
    fields = QgsFields()
    mapa = {}
    usados = set()
    for nombre, tipo, alias in INFO_SYSTEM_FIELDS:
        campo = QgsField(nombre, tipo, _type_name(tipo))
        campo.setAlias(alias)
        fields.append(campo)
        usados.add(nombre)
    _append_schema_fields(fields, mapa, usados, info_schema)
    return fields, mapa


def _append_schema_fields(fields, mapa, usados, schema):
    for attr in S.flatten_attributes(schema):
        # Las fotos y los adjuntos no son columnas: tienen su propio panel y
        # llegan en la fase 4. Meterlos como campo solo estorbaría.
        if S.is_attachment(attr):
            continue
        nombre = S.field_name(attr, usados)
        tipo = _qt_type(attr)
        campo = QgsField(nombre, tipo, _type_name(tipo))
        campo.setAlias(S.field_title(attr))
        if attr.get("description"):
            campo.setComment(str(attr["description"]))
        fields.append(campo)
        mapa[nombre] = attr


def _type_name(tipo):
    """Nombre del tipo que QGIS enseña en las propiedades de la capa.

    Sin él, la columna «Tipo» sale vacía y no hay forma de saber qué guarda
    cada campo mirando la capa.
    """
    return {
        QVariant.String: "string",
        QVariant.StringList: "stringlist",
        QVariant.LongLong: "integer64",
        QVariant.Double: "double",
        QVariant.Bool: "boolean",
    }.get(tipo, "string")


def _qt_type(attr):
    """Tipo de Qt que corresponde al tipo del LAD."""
    tipo = attr.get("type")

    if S.is_multiple(attr):
        # Lista de valores: QGIS tiene tipo lista nativo y lo edita como tal.
        return QVariant.StringList
    if S.is_boolean(attr):
        return QVariant.Bool
    if tipo == "integer":
        return QVariant.LongLong
    if tipo == "number":
        return QVariant.Double
    # Las fechas se quedan como texto a propósito: la API las entrega y las
    # espera en ISO, y convertirlas a QDate obligaría a deshacer la conversión
    # al escribir, con el riesgo de perder la hora o la zona por el camino.
    return QVariant.String


def apply_editor_config(layer, schema):
    """Configura la edición de la capa: widgets, obligatoriedad y solo lectura."""
    form = layer.editFormConfig()
    fields = layer.fields()

    for nombre, _tipo, _alias in SYSTEM_FIELDS:
        idx = fields.indexOf(nombre)
        if idx >= 0:
            form.setReadOnly(idx, True)

    for attr in S.flatten_attributes(schema):
        if S.is_attachment(attr):
            continue
        nombre = attr.get("name")
        idx = fields.indexOf(nombre)
        if idx < 0:
            idx = fields.indexOf(S.RESERVED_PREFIX + str(nombre))
        if idx < 0:
            continue

        setup = _widget_setup(attr)
        if setup is not None:
            layer.setEditorWidgetSetup(idx, setup)

        if not S.is_editable(attr):
            form.setReadOnly(idx, True)

        if S.is_required(attr):
            # Blanda a propósito: hay elementos antiguos con campos ahora
            # obligatorios vacíos, y una restricción dura impediría al técnico
            # guardar cualquier cambio sobre ellos. El servidor sigue teniendo
            # la última palabra.
            layer.setFieldConstraint(
                idx,
                QgsFieldConstraints.ConstraintNotNull,
                QgsFieldConstraints.ConstraintStrengthSoft,
            )

        if attr.get("default_value") is not None:
            layer.setDefaultValueDefinition(
                idx, QgsDefaultValue(S._quote_value(attr["default_value"]))
            )

    layer.setEditFormConfig(form)


def _widget_setup(attr):
    """Widget de edición que le toca a cada tipo del LAD."""
    tipo = attr.get("type")
    valores = S.allowed_values(attr)

    if S.is_boolean(attr):
        return QgsEditorWidgetSetup("CheckBox", {})

    if tipo == "text":
        return QgsEditorWidgetSetup("TextEdit", {"IsMultiline": True})

    if tipo == "calendar":
        return QgsEditorWidgetSetup(
            "DateTime",
            {
                "field_format": "yyyy-MM-dd",
                "display_format": "dd/MM/yyyy",
                "calendar_popup": True,
                "allow_null": True,
            },
        )

    if tipo in S.CHOICE_TYPES and valores:
        if S.is_multiple(attr):
            # QGIS no tiene desplegable de selección múltiple sobre una lista
            # fija sin capa de referencia. Se queda con el editor de lista
            # nativo y la comprobación de valores la hace el servidor.
            return None
        return QgsEditorWidgetSetup(
            "ValueMap", {"map": [{str(v): str(v)} for v in valores]}
        )

    return None


def apply_form(layer, schema):
    """Reconstruye el formulario con sus pestañas y su visibilidad condicional.

    Las secciones del esquema se convierten en pestañas. Un campo con
    ``visible_if`` se envuelve en su propio grupo, porque en QGIS la expresión
    de visibilidad vive en el contenedor y no en el campo suelto.
    """
    form = layer.editFormConfig()
    form.clearTabs()
    fields = layer.fields()

    raiz = schema.get("attributes") if isinstance(schema, dict) else schema
    raiz = raiz or []

    principales = _main_attributes(schema)
    if principales:
        principal = QgsAttributeEditorContainer("Información Principal", None)
        _fill_container(principal, principales, fields)
        form.addTab(principal)

    sueltos = [
        a for a in raiz
        if isinstance(a, dict) and a.get("type") not in S.CONTAINER_TYPES
    ]
    if sueltos:
        general = QgsAttributeEditorContainer("General", None)
        _fill_container(general, sueltos, fields)
        form.addTab(general)

    for contenedor, hijos in S.iter_containers(schema):
        tab = QgsAttributeEditorContainer(S.field_title(contenedor), None)
        expr = _container_visibility(contenedor)
        if expr:
            tab.setVisibilityExpression(QgsOptionalExpression(QgsExpression(expr)))
        _fill_container(tab, hijos, fields)
        form.addTab(tab)

    form.setLayout(QgsEditFormConfig.TabLayout)
    layer.setEditFormConfig(form)


def _main_attributes(schema):
    """Los ``main_attributes`` del esquema, que la web enseña arriba de la ficha.

    Como en la web, se enseñan sin su ``visible_if`` y sin los invisibles; un
    nombre que no esté en el esquema (un campo de sistema) también vale.
    """
    nombres = schema.get("main_attributes") if isinstance(schema, dict) else None
    if not isinstance(nombres, list):
        return []
    definiciones = {}
    for attr in S.flatten_attributes(schema):
        definiciones.setdefault(attr.get("name"), attr)
    return [
        {"name": n, "visible": S.is_visible(definiciones.get(n, {}))}
        for n in nombres
        if isinstance(n, str)
    ]


def add_relations_tab(layer, partes):
    """Pestaña «Información adicional» con los partes de cada tipo.

    Se llama después de :func:`apply_form`, que empieza de cero las pestañas.

    Args:
        partes: pares ``(QgsRelation, tipo)``, con el tipo tal y como viene en
            ``additional_information`` del esquema.
    """
    form = layer.editFormConfig()
    pestaña = QgsAttributeEditorContainer("Información adicional", None)
    for relacion, info in partes:
        # Cada tipo en su grupo, porque en QGIS la visibilidad vive en el
        # contenedor: la web solo ofrece los tipos cuyas dependencias cumple el
        # elemento (un parte de palmeras, solo en las palmeras).
        grupo = QgsAttributeEditorContainer(info.get("title") or info.get("name"), pestaña)
        _as_group_box(grupo)
        expr = _dependencies_expression(info.get("attribute_dependencies"))
        if expr:
            grupo.setVisibilityExpression(QgsOptionalExpression(QgsExpression(expr)))
        hijo = QgsAttributeEditorRelation(relacion, grupo)
        hijo.setRelationWidgetTypeId("relation_editor")
        hijo.setShowLabel(False)
        grupo.addChildElement(hijo)
        pestaña.addChildElement(grupo)
    form.addTab(pestaña)
    layer.setEditFormConfig(form)


def add_media_tab(layer, schema, widget_type):
    """Pestaña «Fotos y archivos» si el esquema tiene campos de fotos o archivos.

    Lleva el campo ``id`` con el tipo de campo del complemento que enseña las
    fotos y archivos del elemento (``gui/media_widget.py``).
    """
    if not any(S.is_attachment(a) for a in S.flatten_attributes(schema)):
        return False
    idx = layer.fields().indexOf("id")
    if idx < 0:
        return False
    layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup(widget_type, {}))
    form = layer.editFormConfig()
    pestaña = QgsAttributeEditorContainer("Fotos y archivos", None)
    campo = QgsAttributeEditorField("id", idx, pestaña)
    campo.setShowLabel(False)
    pestaña.addChildElement(campo)
    form.addTab(pestaña)
    layer.setEditFormConfig(form)
    return True


def _dependencies_expression(dependencias):
    """Como ``availableTabs`` de FeatureInfo.jsx: todas, sin mayúsculas ni espacios."""
    if not isinstance(dependencias, list):
        return None
    partes = [
        f"lower(trim(to_string({S._quote_field(d['name'])}))) = "
        f"{S._quote_value(str(d.get('value', '')).strip().lower())}"
        for d in dependencias
        if isinstance(d, dict) and d.get("name")
    ]
    return " AND ".join(f"coalesce({p}, FALSE)" for p in partes) or None


def _fill_container(contenedor, atributos, fields):
    """Vuelca atributos en un contenedor, anidando las subsecciones."""
    for attr in atributos:
        if not isinstance(attr, dict):
            continue

        if attr.get("type") in S.CONTAINER_TYPES:
            hijo = QgsAttributeEditorContainer(S.field_title(attr), contenedor)
            _as_group_box(hijo)
            expr = _container_visibility(attr)
            if expr:
                hijo.setVisibilityExpression(
                    QgsOptionalExpression(QgsExpression(expr))
                )
            _fill_container(hijo, attr.get("contents") or [], fields)
            contenedor.addChildElement(hijo)
            continue

        # «visible: false» es un campo que la web no enseña en la ficha. Se
        # queda en la tabla de atributos, que hace de «Mostrar campos invisibles».
        if S.is_attachment(attr) or not S.is_visible(attr):
            continue

        nombre = attr.get("name")
        idx = fields.indexOf(nombre)
        if idx < 0:
            nombre = S.RESERVED_PREFIX + str(nombre)
            idx = fields.indexOf(nombre)
        if idx < 0:
            continue

        campo = QgsAttributeEditorField(nombre, idx, contenedor)

        expr = S.visible_if_to_expression(attr.get("visible_if"))
        if expr:
            envoltorio = QgsAttributeEditorContainer("", contenedor)
            _as_group_box(envoltorio)
            envoltorio.setVisibilityExpression(
                QgsOptionalExpression(QgsExpression(expr))
            )
            campo = QgsAttributeEditorField(nombre, idx, envoltorio)
            envoltorio.addChildElement(campo)
            contenedor.addChildElement(envoltorio)
        else:
            contenedor.addChildElement(campo)


def _as_group_box(contenedor):
    """Marca un contenedor como grupo.

    ``setIsGroupBox`` quedó obsoleto en QGIS 3.40 a favor de ``setType``, pero
    la versión mínima que soportamos es la 3.34, así que se usa el que haya.
    """
    tipos = getattr(Qgis, "AttributeEditorContainerType", None)
    if tipos is not None and hasattr(contenedor, "setType"):
        contenedor.setType(tipos.GroupBox)
    else:
        contenedor.setIsGroupBox(True)


def _container_visibility(contenedor):
    """Expresión de visibilidad de una sección.

    ``section_decision`` la trae en ``depends`` con la forma
    ``{"name": campo, "value": valor}``; el resto puede traer un ``visible_if``
    normal.
    """
    depends = contenedor.get("depends")
    if isinstance(depends, dict) and depends.get("name"):
        return S.visible_if_to_expression(
            {
                "field": depends["name"],
                "operator": "equals",
                "value": depends.get("value"),
            }
        )
    return S.visible_if_to_expression(contenedor.get("visible_if"))


def unique_values_from_schema(attr):
    """Valores únicos que se pueden dar sin preguntar al servidor.

    Cuando el atributo declara sus valores permitidos, esa lista **es** el
    conjunto de valores únicos y no hace falta recorrer la capa. Es lo que
    evita que abrir la simbología graduada descargue cien mil elementos.
    """
    return S.allowed_values(attr)
