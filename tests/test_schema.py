"""Pruebas del lector de esquemas. No necesitan QGIS.

Los esquemas de ejemplo reproducen la forma real de los que hay en producción,
incluidas las secciones anidadas y los tipos menos frecuentes.
"""

from geosian.core import schema as S

ESQUEMA = {
    "name": "arbolado",
    "title": "Arbolado",
    "attributes": [
        {"name": "codigo", "type": "string", "title": "Código", "required": True},
        {"name": "object_id", "type": "string", "title": "ID", "editable": False},
        {
            "name": "page_section_1",
            "type": "page_section",
            "title": "Localización",
            "contents": [
                {"name": "distrito", "type": "select", "title": "Zona",
                 "allowed_values": ["CENTRO", "PELAYO"]},
                {
                    "name": "seccion_anidada",
                    "type": "section",
                    "title": "Detalle",
                    "contents": [
                        {"name": "acera", "type": "number", "title": "Acera (m)"},
                    ],
                },
            ],
        },
        {
            "name": "section_decision_1",
            "type": "section_decision",
            "title": "Arbolado",
            "depends": {"name": "porte", "value": "arbol"},
            "contents": [
                {"name": "altura", "type": "number", "title": "Altura"},
            ],
        },
        {"name": "pictures", "type": "images", "title": "Fotos"},
    ],
}


def test_aplana_secciones_anidadas():
    nombres = [a["name"] for a in S.flatten_attributes(ESQUEMA)]
    assert nombres == [
        "codigo",
        "object_id",
        "distrito",
        "acera",
        "altura",
        "pictures",
    ]


def test_guarda_la_ruta_de_secciones():
    porNombre = {a["name"]: a for a in S.flatten_attributes(ESQUEMA)}
    ruta = [s["name"] for s in porNombre["acera"]["_path"]]
    assert ruta == ["page_section_1", "seccion_anidada"]
    assert porNombre["codigo"]["_path"] == []


def test_clasificacion_de_tipos():
    assert S.is_attachment({"type": "images"})
    assert S.is_attachment({"type": "files"})
    assert not S.is_attachment({"type": "string"})

    assert S.is_multiple({"type": "checkbox", "allowed_values": ["a", "b"]})
    assert S.is_multiple({"type": "select", "multiple": True})
    assert not S.is_multiple({"type": "select"})

    assert S.is_boolean({"type": "checkbox"})
    assert not S.is_boolean({"type": "checkbox", "allowed_values": ["a"]})


def test_nombres_reservados():
    usados = set()
    assert S.field_name({"name": "id"}, usados) == "attr__id"
    assert S.field_name({"name": "codigo"}, usados) == "codigo"
    # Un segundo campo con el mismo nombre no puede pisar al primero.
    assert S.field_name({"name": "codigo"}, usados) == "codigo_2"


def test_allowed_values_dinamicos_no_rompen():
    # Si llegara sin resolver, el campo se queda como texto libre.
    assert S.allowed_values({"allowed_values": {"depends_on": "x", "mapping": {}}}) == []
    assert S.allowed_values({"allowed_values": ["a", "b"]}) == ["a", "b"]


# ----------------------------------------------------------------------
# Visibilidad condicional
# ----------------------------------------------------------------------

def test_equals_cubre_escalar_y_lista():
    expr = S.visible_if_to_expression(
        {"field": "operacion", "operator": "equals", "value": "Instalación anclaje"}
    )
    assert '"operacion"' in expr
    assert "array_contains" in expr          # el caso lista
    assert "'Instalación anclaje'" in expr   # el caso escalar


def test_contains_any():
    expr = S.visible_if_to_expression(
        {"field": "ops", "operator": "contains_any", "values": ["a", "b"]}
    )
    assert "IN ('a', 'b')" in expr
    assert "array_contains" in expr


def test_contains_all():
    expr = S.visible_if_to_expression(
        {"field": "ops", "operator": "contains_all", "values": ["a", "b"]}
    )
    assert expr.count("array_contains") == 2
    assert " AND " in expr


def test_comparaciones_numericas():
    expr = S.visible_if_to_expression(
        {"field": "altura", "operator": "greater_than", "value": 5}
    )
    assert "to_real(\"altura\") > 5.0" in expr


def test_is_empty_replica_al_frontend():
    # El frontend descarta el campo antes de llegar al operador, así que
    # is_empty nunca se cumple. Aquí se replica esa semántica.
    expr = S.visible_if_to_expression({"field": "x", "operator": "is_empty"})
    assert "FALSE" in expr


def test_operador_desconocido_no_traduce():
    assert S.visible_if_to_expression({"field": "x", "operator": "regex"}) is None
    assert S.visible_if_to_expression(None) is None
    assert S.visible_if_to_expression({"operator": "equals"}) is None


def test_comillas_en_valores():
    expr = S.visible_if_to_expression(
        {"field": "obs", "operator": "equals", "value": "L'Hospitalet"}
    )
    assert "'L''Hospitalet'" in expr
