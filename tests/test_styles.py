"""Pruebas de la simbología de Geosian. No necesitan QGIS."""

from geosian.core import styles


def test_hex_como_el_frontal():
    assert styles.hex_to_rgba("#ff7300") == (255, 115, 0, 230)
    assert styles.hex_to_rgba("#37935C80") == (55, 147, 92, 128)
    # Lo que el frontal no entiende sale negro opaco, igual que allí.
    assert styles.hex_to_rgba("red") == (0, 0, 0, 255)
    assert styles.hex_to_rgba("#abc") == (0, 0, 0, 255)


def test_sin_estilos_usa_el_color_de_la_geometria():
    esquema = {"attributes": [{"name": "nombre", "type": "text"}]}
    assert styles.base_style(esquema, "points")["default"] == styles.FALLBACK_POINT
    assert styles.base_style(esquema, "multi_points")["default"] == styles.FALLBACK_MULTIPOINT
    assert styles.base_style(esquema, "multi_lines")["default"] == styles.FALLBACK_LINE
    # Polígonos sin ningún estilo de geometrías: el violeta opaco de la web
    # (getGeometryStyleColors devuelve POLYGON_COLORS[0], alfa 255).
    assert styles.base_style(esquema, "polygons")["default"] == (238, 130, 238, 255)
    assert styles.base_style({"styles": {"geometries": None}}, "multi_polygons")["default"] == (238, 130, 238, 255)
    # Con el bloque de geometrías, aunque no diga nada del polígono: opacidad 0,5.
    assert styles.base_style({"styles": {"geometries": {}}}, "polygons")["default"] == (238, 130, 238, 128)


def test_una_capa_sin_esquema_sale_gris_como_en_la_web():
    # getFeatureColor: sin esquema, gris (128, 128, 128, 230) para cualquier geometría.
    for tipo in ("points", "multi_points", "lines", "polygons", "multi_polygons"):
        assert styles.base_style({}, tipo)["default"] == (128, 128, 128, 230)
        assert styles.base_style(None, tipo)["default"] == (128, 128, 128, 230)


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


def test_vista_graduada_no_repite_etiquetas():
    config = {"color": {"mode": "graduated", "attribute": "s", "breaks": [0, 50, 150],
                        "colors": [[1, 1, 1], [2, 2, 2], [3, 3, 3]],
                        "labels": ["< 50", "50 – 150", "≥ 150"]}}
    etiquetas = [e for _, _, _, e in styles.view_style(config, "polygons")["ranges"]]
    assert etiquetas == ["< 0", "< 50", "50 – 150", "≥ 150"]


def test_vista_sin_color_usa_el_estilo_de_la_capa():
    vista = styles.view_style({"visualization": "default"}, "points", {})
    assert vista["kind"] == "base"


def test_visualizaciones_sin_equivalente_se_avisan():
    # Todas las de la web tienen ya su equivalente; una desconocida sigue avisando.
    vista = styles.view_style({"visualization": "algo_nuevo", "color": {"value": [1, 2, 3]}}, "points")
    assert vista["unsupported"] == "algo_nuevo"
    assert vista["kind"] == "single"
    # Los hexágonos ya tienen su equivalente: las teselas agregadas del servidor.
    assert styles.view_style({"visualization": "hexagon"}, "points")["kind"] == "hexagon"
    assert styles.view_style({"visualization": "heatmap"}, "points")["kind"] == "heatmap"


def test_expresiones_de_reglas():
    grupo = {"operator": "or", "rules": [
        {"field": "riesgo", "operator": "in", "value": ["Alto", "Muy alto"]},
        {"field": "altura", "operator": "gte", "value": 10},
    ]}
    assert styles.filter_group_expression(grupo) == (
        "(coalesce(to_string(\"riesgo\") IN ('Alto', 'Muy alto'), FALSE)"
        " OR coalesce(to_real(\"altura\") >= 10.0, FALSE))"
    )
    # Sin condiciones casa siempre; con un operador desconocido, nunca (como la web).
    assert styles.filter_group_expression({"rules": []}) == "TRUE"
    assert styles.filter_group_expression(
        {"rules": [{"field": "a", "operator": "raro", "value": 1}]}) == "(coalesce(FALSE, FALSE))"


def test_etiqueta_por_defecto_como_la_web():
    esquema = {
        "attributes_on_map": ["riesgo"],
        "attributes": [
            {"name": "codigo", "type": "string", "label": True},  # no está en el mapa
            {"name": "seccion", "type": "section", "contents": [
                {"name": "riesgo", "type": "select", "label": True},
            ]},
        ],
    }
    assert styles.label_attribute(esquema) == "riesgo"
    assert styles.label_attribute({"attributes": [{"name": "a", "label": True}]}) is None


def test_etiquetas_que_se_pueden_encender_como_la_web():
    # LabelSelector.jsx ofrece los atributos que declaran «label», esté a true o
    # a false, también dentro de secciones; los demás no.
    esquema = {
        "attributes": [
            {"name": "codigo", "title": "Código", "type": "string", "label": False},
            {"name": "altura", "title": "Altura", "type": "number"},
            {
                "name": "s1",
                "type": "section",
                "title": "Detalle",
                "contents": [{"name": "especie", "title": "Especie", "type": "select", "label": True}],
            },
        ]
    }

    assert styles.label_choices(esquema) == [("codigo", "Código"), ("especie", "Especie")]
    assert styles.label_choices({}) == []


def test_las_rampas_son_las_de_la_web():
    """Valores sacados de ``generatePalette`` de ``colorRamps.js`` (la web), con node."""
    assert styles.ramp_colors("viridis", 6) == [
        (68, 1, 84, 230), (61, 66, 128, 230), (43, 120, 140, 230),
        (57, 167, 123, 230), (126, 207, 86, 230), (253, 231, 37, 230)]
    assert styles.ramp_colors("plasma", 6) == [
        (13, 8, 135, 230), (103, 4, 161, 230), (173, 44, 139, 230),
        (222, 102, 98, 230), (246, 169, 58, 230), (240, 249, 33, 230)]
    # «oranges» faltaba: el editor de vistas la ofrece.
    assert styles.ramp_colors("oranges", 6) == [
        (255, 245, 235, 230), (254, 219, 176, 230), (253, 169, 100, 230),
        (239, 113, 36, 230), (199, 65, 2, 230), (127, 39, 4, 230)]
    # Menos colores que la rampa: equidistantes, sin interpolar.
    assert styles.ramp_colors("reds", 3) == [(255, 245, 240, 230), (251, 106, 74, 230), (103, 0, 13, 230)]
    assert styles.ramp_colors("category10", 4) == [
        (31, 119, 180, 230), (214, 39, 40, 230), (227, 119, 194, 230), (23, 190, 207, 230)]
