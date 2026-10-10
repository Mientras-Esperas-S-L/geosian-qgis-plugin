"""Árbol de capas de un mapa, como el panel de GCC. No necesita QGIS."""

from geosian.core import maptree


def test_orden_carpetas_y_capas_sueltas_al_final():
    ajustes = {
        "settings": {
            "layer_order": [3, "group:g1", 99],
            "layer_groups": {
                "g1": {"name": "Riego", "expanded": False, "children": ["group:g2", 1]},
                "g2": {"name": "Tuberías", "layerIds": [2]},  # formato antiguo
            },
        }
    }
    assert maptree.layer_tree(ajustes, [1, 2, 3, 4]) == [
        ("layer", 3),
        ("group", "Riego", False, [("group", "Tuberías", True, [("layer", 2)]), ("layer", 1)]),
        ("layer", 4),  # no estaba en el árbol: al final, no desaparece
    ]


def test_en_modo_basico_manda_la_estructura_publicada():
    ajustes = {
        "settings": {"layer_order": [2, 1]},
        "map_structure": {"layer_order": [1, 2], "layer_groups": {}},
    }
    assert maptree.layer_tree(ajustes, [1, 2]) == [("layer", 1), ("layer", 2)]
    ajustes["settings"]["layer_panel_mode"] = "advanced"
    assert maptree.layer_tree(ajustes, [1, 2]) == [("layer", 2), ("layer", 1)]


def test_carpetas_en_bucle_no_cuelgan():
    ajustes = {"settings": {"layer_order": ["group:a"], "layer_groups": {
        "a": {"name": "A", "children": ["group:b"]},
        "b": {"name": "B", "children": ["group:a", 1]},
    }}}
    assert maptree.layer_tree(ajustes, [1]) == [
        ("group", "A", True, [("group", "B", True, [("layer", 1)])])
    ]


def test_capas_apagadas_y_vistas_activas():
    ajustes = {"settings": {"visible_layers": {"5": False, "6": True},
                            "active_view_ids": [70, 71, 99]}}
    assert maptree.hidden_layers(ajustes) == {5}
    vistas = {5: [{"id": 70, "name": "a"}, {"id": 71, "name": "b"}]}
    # Una vista por capa, la primera; la 99 ya no existe.
    assert maptree.active_views(ajustes, vistas) == {5: {"id": 70, "name": "a"}}


def test_sin_ajustes():
    assert maptree.layer_tree({}, [2, 1]) == [("layer", 2), ("layer", 1)]
    assert maptree.hidden_layers({}) == set()
    assert maptree.active_views({}, {}) == {}
