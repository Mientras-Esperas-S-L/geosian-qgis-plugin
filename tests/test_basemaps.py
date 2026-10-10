"""Mapas base, sin QGIS delante."""

from geosian.core import basemaps


def test_origen_de_la_aplicacion_a_partir_de_la_api():
    assert basemaps.app_origin("https://api.devel.greencitycontrol.com") == "https://app.devel.greencitycontrol.com"
    assert basemaps.app_origin("https://api.greencitycontrol.com/") == "https://app.greencitycontrol.com"
    # Sin «api.» no se adivina: el de producción, que es público.
    assert basemaps.app_origin("http://localhost:8010") == basemaps.APP_POR_DEFECTO


def test_estilo_geosian_con_las_teselas_de_la_aplicacion():
    estilo = basemaps.geosian_style("https://api.devel.greencitycontrol.com")
    assert estilo["sources"]["omt"]["tiles"] == [
        "https://app.devel.greencitycontrol.com/teselas/espana/{z}/{x}/{y}?v=2"
    ]
    assert len(estilo["layers"]) > 30
    assert estilo["layers"][0]["type"] == "background"


def test_fondos_propios_del_mapa():
    fondos = [
        {"code": "ORTO", "name": "Ortofoto", "kind": "xyz", "min_zoom": 0, "max_zoom": 20,
         "tiles": ["https://ejemplo.org/orto/{z}/{x}/{y}.jpg"]},
        {"code": "AYTO", "name": "Ortofoto municipal", "kind": "wms", "max_zoom": 21,
         "tiles": ["/fondos/AYTO/{z}/{x}/{y}"]},
        {"code": "VEC", "name": "Callejero", "kind": "style", "style_url": "https://ejemplo.org/estilo.json"},
        {"code": "ROTO", "name": "Sin teselas", "kind": "xyz"},
    ]

    capas = basemaps.layer_specs(fondos, "https://api.devel.greencitycontrol.com")

    assert capas == [
        {"name": "Ortofoto", "type": "raster", "url": "https://ejemplo.org/orto/{z}/{x}/{y}.jpg", "zmin": 0, "zmax": 20},
        # La ruta del proxy es relativa a la aplicación, como hace el frontal.
        {"name": "Ortofoto municipal", "type": "raster",
         "url": "https://app.devel.greencitycontrol.com/fondos/AYTO/{z}/{x}/{y}", "zmin": 0, "zmax": 21},
        {"name": "Callejero", "type": "style", "url": "https://ejemplo.org/estilo.json"},
    ]


def test_estilo_oscuro_y_de_calles_con_las_teselas_de_la_aplicacion():
    for variante in ("oscuro", "calles"):
        estilo = basemaps.geosian_style("https://api.devel.greencitycontrol.com", variante)
        assert estilo["sources"]["omt"]["tiles"] == [
            "https://app.devel.greencitycontrol.com/teselas/espana/{z}/{x}/{y}?v=2"
        ]
        assert list(estilo["sources"]) == ["omt"]
    oscuro = basemaps.geosian_style("https://api.devel.greencitycontrol.com", "oscuro")
    assert oscuro["layers"][0]["type"] == "background"


def test_fondos_fijos_del_selector_de_la_web():
    fijos = basemaps.fixed_basemaps("https://api.devel.greencitycontrol.com")
    assert [f["name"] for f in fijos] == ["Ortofoto (IGN)", "mapa base oscuro"]
    foto, oscuro = fijos
    # La ortofoto por el proxy de la aplicación, como la web, con las calles encima.
    assert foto["url"] == "https://app.devel.greencitycontrol.com/ortofoto/{z}/{x}/{y}"
    assert foto["zmax"] == 20
    assert foto["calles"]["sources"]["omt"]["tiles"][0].startswith("https://app.devel.")
    assert oscuro["style"]["layers"]
