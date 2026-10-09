"""Traducción de los filtros de las vistas. No necesita QGIS."""

from geosian.core import views


def _grupo(*reglas, contexto="elements", **extra):
    return {"query_groups": [{"context": contexto, "operator": "and", "rules": list(reglas), **extra}]}


def test_in_y_rangos_como_el_frontal():
    params, avisos = views.filter_params(
        _grupo(
            {"field": "Especie", "operator": "in", "value": ["Prunus dulcis", "Olea"]},
            {"field": "diametro", "operator": "gte", "value": "10"},
            {"field": "diametro", "operator": "lte", "value": "90"},
            {"field": "nombre", "operator": "contains", "value": "ol"},
            {"field": "regado", "operator": "equals", "value": True},
        )
    )
    assert params == {
        "attr__Especie": ["Prunus dulcis", "Olea"],
        "attr__diametro__gte": "10",
        "attr__diametro__lte": "90",
        "attr__nombre__contains": "ol",
        "attr__regado": "true",
    }
    assert avisos == []


def test_operadores_que_la_web_descarta_se_avisan():
    params, avisos = views.filter_params(_grupo({"field": "a", "operator": "starts_with", "value": "x"}))
    assert params == {}
    assert len(avisos) == 1


def test_informacion_adicional_y_global():
    config = {
        "query_groups": [
            {"context": "additional_info", "source_name": "poda", "operator": "and",
             "rules": [{"field": "tipo", "operator": "in", "value": ["Total"]}]},
            {"context": "global", "operator": "and",
             "rules": [{"field": "_created_at", "operator": "gte", "value": "2026-01-01"},
                       {"field": "_most_recent", "operator": "equals", "value": True}]},
        ]
    }
    params, _ = views.filter_params(config)
    assert params["attr__poda__tipo"] == ["Total"]
    assert params["date_from"] == "2026-01-01"
    assert params["most_recent"] == "true"


def test_vista_vacia_no_filtra():
    assert views.filter_params({}) == ({}, [])
    assert views.filter_params({"query_groups": []}) == ({}, [])


def test_vistas_de_informacion_adicional_no_son_de_elementos():
    assert views.is_element_view({"context_type": "elements"})
    assert not views.is_element_view({"context_type": "additional_info"})


def test_superposicion_o_sustitucion_como_la_web():
    assert not views.is_overlay({})
    assert not views.is_overlay({"visualization": "default", "mode": "categorized"})
    assert views.is_overlay({"visualization": "icon"})
    assert views.is_overlay({"visualization": "heatmap"})
