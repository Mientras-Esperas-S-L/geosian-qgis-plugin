"""Pruebas de la simbología de Geosian. No necesitan QGIS."""

from geosian.core import styles


def test_hex_como_el_frontal():
    assert styles.hex_to_rgba("#ff7300") == (255, 115, 0, 230)
    assert styles.hex_to_rgba("#37935C80") == (55, 147, 92, 128)
    # Lo que el frontal no entiende sale negro opaco, igual que allí.
    assert styles.hex_to_rgba("red") == (0, 0, 0, 255)
    assert styles.hex_to_rgba("#abc") == (0, 0, 0, 255)


def test_sin_estilos_usa_el_color_de_la_geometria():
    assert styles.base_style({}, "points")["default"] == styles.FALLBACK_POINT
    assert styles.base_style({}, "multi_points")["default"] == styles.FALLBACK_MULTIPOINT
    assert styles.base_style({}, "multi_lines")["default"] == styles.FALLBACK_LINE
    # Polígonos: violeta con la opacidad de relleno por defecto (0,5).
    assert styles.base_style({}, "polygons")["default"] == (238, 130, 238, 128)


def test_estilo_de_poligono_del_lad_con_su_opacidad():
    esquema = {
        "styles": {
            "geometries": {"polyStyle": {"fill-color": "#37935CFF", "fill-opacity": 0.25}}
        }
    }
    assert styles.base_style(esquema, "multi_polygons")["default"] == (55, 147, 92, 64)


def test_reglas_por_prioridad_y_exclusion_de_las_anteriores():
    esquema = {
        "styles": {
            "colors": [
                {"attribute": "riesgo", "priority": 1, "default": "#808080",
                 "allowed_values": {"Alto": "#ff7300"}},
                {"attribute": "marked_as", "priority": 0,
                 "allowed_values": {"Riego": "#34afff"}},
            ]
        }
    }
    estilo = styles.base_style(esquema, "points")
    # Primero la de prioridad 0, y la de riesgo excluye lo que ya cayó en ella.
    assert [(r["attribute"], r["value"]) for r in estilo["rules"]] == [
        ("marked_as", "Riego"),
        ("riesgo", "Alto"),
    ]
    assert estilo["rules"][0]["excluded"] == []
    assert estilo["rules"][1]["excluded"] == [("marked_as", ["Riego"])]
    # El defecto es el de la regla de más prioridad que lo tiene.
    assert estilo["default"] == (128, 128, 128, 230)


def test_vista_categorizada():
    config = {
        "mode": "categorized",
        "color": {
            "mode": "categorized",
            "attribute": "riesgo",
            "categories": {"Alto": {"color": [31, 119, 180, 230], "label": "Alto"}},
            "default": {"color": [158, 158, 158, 230], "label": "Otros"},
        },
    }
    vista = styles.view_style(config, "points")
    assert vista["kind"] == "categorized"
    assert vista["categories"] == [("Alto", (31, 119, 180, 230), "Alto")]
    assert vista["default"] == (158, 158, 158, 230)


def test_vista_graduada_con_tramos_abiertos():
    config = {"color": {"mode": "graduated", "attribute": "altura",
                        "breaks": [0, 10], "colors": [[1, 1, 1], [2, 2, 2]]}}
    tramos = styles.view_style(config, "points")["ranges"]
    assert [(d, h) for d, h, _, _ in tramos] == [(None, 0.0), (0.0, 10.0), (10.0, None)]
    # Por debajo del primer corte, el primer color; por encima, el último.
    assert [c[:3] for _, _, c, _ in tramos] == [(1, 1, 1), (1, 1, 1), (2, 2, 2)]


def test_vista_sin_color_usa_el_estilo_de_la_capa():
    vista = styles.view_style({"visualization": "default"}, "points", {})
    assert vista["kind"] == "base"


def test_visualizaciones_sin_equivalente_se_avisan():
    vista = styles.view_style({"visualization": "hexagon", "color": {"value": [1, 2, 3]}}, "points")
    assert vista["unsupported"] == "hexagon"
    assert vista["kind"] == "single"
    assert styles.view_style({"visualization": "heatmap"}, "points")["kind"] == "heatmap"


def test_expresiones_de_reglas():
    grupo = {"operator": "or", "rules": [
        {"field": "riesgo", "operator": "in", "value": ["Alto", "Muy alto"]},
        {"field": "altura", "operator": "gte", "value": 10},
    ]}
    assert styles.filter_group_expression(grupo) == (
        "(to_string(\"riesgo\") IN ('Alto', 'Muy alto') OR to_real(\"altura\") >= 10.0)"
    )
