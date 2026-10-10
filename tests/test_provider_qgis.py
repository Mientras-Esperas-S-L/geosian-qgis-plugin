"""Prueba de punta a punta del proveedor, con QGIS de verdad.

Levanta un servidor que responde como Geosian, registra el proveedor, abre una
capa y comprueba lo que vería el técnico: campos, datos, geometrías, formulario
y valores de los desplegables.

Se ejecuta con el Python que tenga PyQGIS:

    QT_QPA_PLATFORM=offscreen pytest tests/test_provider_qgis.py
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import (
    QgsFeatureRequest,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)

from geosian.core import connections, lad
from tests.fake_server import FakeGeosian

CONEXION = "PruebaAutomatica"


@pytest.fixture
def servidor(app):
    with FakeGeosian() as fake:
        connections.save_connection(
            CONEXION, fake.url, "tecnico@ejemplo.com"
        )
        connections.set_session(CONEXION, "tok-de-prueba", "jwt-de-prueba")
        yield fake
        connections.remove_connection(CONEXION)


@pytest.fixture
def capa(servidor):
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points"
    vectorial = QgsVectorLayer(uri, "Arbolado", "geosian")
    assert vectorial.isValid(), vectorial.dataProvider().error()
    return vectorial


# ----------------------------------------------------------------------
# Apertura de la capa
# ----------------------------------------------------------------------

def test_la_capa_abre_y_es_de_puntos(capa):
    assert capa.isValid()
    assert capa.wkbType() == QgsWkbTypes.Point
    assert capa.dataProvider().storageType() == "Geosian REST API"


def test_campos_salen_del_esquema(capa):
    nombres = [c.name() for c in capa.fields()]

    # Campos de sistema primero.
    assert nombres[0] == "id"
    assert "object_id" in nombres
    assert "updated_at" in nombres

    # Los del esquema, con su alias.
    assert "codigo" in nombres
    assert "especie" in nombres
    assert "altura" in nombres
    assert capa.fields().field("altura").alias() == "Altura (m)"

    # Las fotos no son un campo.
    assert "pictures" not in nombres

    # Un atributo del esquema llamado "id" chocaría con el de sistema, así que
    # se renombra en vez de pisarlo.
    assert "attr__id" in nombres

    # Los campos de dentro de una sección también están.
    assert "operacion" in nombres
    assert "nuevo_riesgo" in nombres


def test_tipos_de_campo(capa):
    from qgis.PyQt.QtCore import QVariant

    campos = capa.fields()
    assert campos.field("altura").type() == QVariant.Double
    assert campos.field("attr__id").type() == QVariant.LongLong
    # Un checkbox múltiple es una lista, no un texto suelto.
    assert campos.field("operacion").type() == QVariant.StringList
    # Y el tipo tiene nombre, para que se vea en las propiedades de la capa.
    assert campos.field("altura").typeName() == "double"


def test_extension_y_recuento_sin_descargar(servidor):
    """El recuento y la extensión salen de los metadatos, no de los datos."""
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points"
    vectorial = QgsVectorLayer(uri, "Arbolado", "geosian")

    assert vectorial.featureCount() == 3
    extension = vectorial.extent()
    assert round(extension.xMinimum(), 2) == -3.72

    # Nadie pidió los datos todavía.
    assert "/api/v1/geodata/paginated/" not in servidor.rutas_pedidas()


# ----------------------------------------------------------------------
# Lectura
# ----------------------------------------------------------------------

def test_lee_los_elementos(capa):
    elementos = list(capa.getFeatures())
    assert len(elementos) == 3

    por_id = {f.id(): f for f in elementos}
    primero = por_id[1001]
    assert primero["codigo"] == "A-001"
    assert primero["especie"] == "Platanus x hispanica"
    assert primero["altura"] == 12.5
    assert primero["object_id"] == "OBJ-1001"
    assert primero.hasGeometry()
    assert round(primero.geometry().asPoint().x(), 2) == -3.70


def test_elemento_sin_geometria_no_rompe(capa):
    sin_geom = {f.id(): f for f in capa.getFeatures()}[1003]
    assert not sin_geom.hasGeometry()
    assert sin_geom["codigo"] == "A-003"


def test_identify_por_identificador(capa):
    peticion = QgsFeatureRequest().setFilterFid(1002)
    elementos = list(capa.getFeatures(peticion))
    assert len(elementos) == 1
    assert elementos[0]["codigo"] == "A-002"


def test_filtro_por_recuadro(capa):
    # Encierra al 1002 (-3.71, 40.41) y deja fuera al 1001 (-3.70, 40.40).
    recuadro = QgsRectangle(-3.715, 40.405, -3.705, 40.415)
    elementos = list(capa.getFeatures(QgsFeatureRequest().setFilterRect(recuadro)))
    assert [f.id() for f in elementos] == [1002]


def test_peticion_sin_geometria(capa):
    peticion = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
    for elemento in capa.getFeatures(peticion):
        assert not elemento.hasGeometry()
        assert elemento["codigo"]  # los atributos sí vienen


def test_limite(capa):
    elementos = list(capa.getFeatures(QgsFeatureRequest().setLimit(2)))
    assert len(elementos) == 2


# ----------------------------------------------------------------------
# Agregaciones
# ----------------------------------------------------------------------

def test_valores_unicos_salen_del_esquema_sin_pedir_datos(servidor):
    """La simbología graduada no puede descargarse la capa entera."""
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points"
    vectorial = QgsVectorLayer(uri, "Arbolado", "geosian")

    idx = vectorial.fields().indexOf("especie")
    valores = vectorial.dataProvider().uniqueValues(idx)

    assert valores == {"Platanus x hispanica", "Tilia platyphyllos"}
    assert "/api/v1/geodata/paginated/" not in servidor.rutas_pedidas()


def test_valores_unicos_de_campo_libre_usan_los_datos(capa):
    idx = capa.fields().indexOf("codigo")
    valores = capa.dataProvider().uniqueValues(idx)
    assert valores == {"A-001", "A-002", "A-003"}


def test_minimo_y_maximo(capa):
    idx = capa.fields().indexOf("altura")
    assert capa.dataProvider().minimumValue(idx) == 8.0
    assert capa.dataProvider().maximumValue(idx) == 12.5


# ----------------------------------------------------------------------
# Formulario
# ----------------------------------------------------------------------

def test_el_formulario_tiene_las_secciones_del_esquema(capa):
    esquema = capa.dataProvider().schema
    lad.apply_editor_config(capa, esquema)
    lad.apply_form(capa, esquema)

    titulos = [t.name() for t in capa.editFormConfig().tabs()]
    assert "General" in titulos
    assert "Riesgo" in titulos


def test_campo_condicional_lleva_su_expresion(capa):
    esquema = capa.dataProvider().schema
    lad.apply_form(capa, esquema)

    riesgo = next(t for t in capa.editFormConfig().tabs() if t.name() == "Riesgo")
    expresiones = [
        hijo.visibilityExpression().data().expression()
        for hijo in riesgo.children()
        if hasattr(hijo, "visibilityExpression")
        and hijo.visibilityExpression().enabled()
    ]
    assert any("operacion" in e for e in expresiones)
    assert any("Instalación anclaje" in e for e in expresiones)


def test_campo_invisible_no_sale_en_el_formulario(capa):
    # La web oculta los «visible: false» salvo con «Mostrar campos invisibles».
    lad.apply_form(capa, capa.dataProvider().schema)

    def nombres(contenedor):
        for hijo in contenedor.children():
            if hasattr(hijo, "children"):
                yield from nombres(hijo)
            else:
                yield hijo.name()

    en_formulario = {n for t in capa.editFormConfig().tabs() for n in nombres(t)}
    assert "observaciones" in en_formulario
    assert "codigo_migracion" not in en_formulario
    assert capa.fields().indexOf("codigo_migracion") >= 0  # sigue en la tabla


def test_atributos_principales_van_en_la_primera_pestana(capa):
    # La web los pone arriba, en «Información Principal», sin los invisibles.
    lad.apply_form(capa, capa.dataProvider().schema)

    primera = capa.editFormConfig().tabs()[0]
    assert primera.name() == "Información Principal"
    assert [h.name() for h in primera.children()] == ["object_id", "especie"]


def test_desplegable_de_valores_permitidos(capa):
    lad.apply_editor_config(capa, capa.dataProvider().schema)
    idx = capa.fields().indexOf("especie")
    setup = capa.editorWidgetSetup(idx)
    assert setup.type() == "ValueMap"
    valores = [next(iter(d.values())) for d in setup.config()["map"]]
    assert "Tilia platyphyllos" in valores


def test_campos_de_sistema_son_de_solo_lectura(capa):
    lad.apply_editor_config(capa, capa.dataProvider().schema)
    config = capa.editFormConfig()
    for nombre in ("id", "object_id", "updated_at"):
        assert config.readOnly(capa.fields().indexOf(nombre))


def test_campo_no_editable_del_esquema(capa):
    lad.apply_editor_config(capa, capa.dataProvider().schema)
    idx = capa.fields().indexOf("object_id")
    assert capa.editFormConfig().readOnly(idx)


# ----------------------------------------------------------------------
# Estado y errores
# ----------------------------------------------------------------------

def test_fase_1_es_solo_lectura(capa):
    from qgis.core import QgsVectorDataProvider

    capacidades = capa.dataProvider().capabilities()
    assert not capacidades & QgsVectorDataProvider.AddFeatures
    assert not capacidades & QgsVectorDataProvider.ChangeAttributeValues
    assert not capacidades & QgsVectorDataProvider.DeleteFeatures


def test_recargar_vacia_la_cache(capa, servidor):
    list(capa.getFeatures())
    antes = servidor.rutas_pedidas().count("/api/v1/geodata/paginated/")

    capa.dataProvider().reloadData()
    list(capa.getFeatures())
    despues = servidor.rutas_pedidas().count("/api/v1/geodata/paginated/")

    assert despues > antes


def test_login_por_la_pila_de_red_de_qgis(app):
    """El POST del login tiene que funcionar con el transporte de QGIS.

    No vale probarlo solo con el transporte de la biblioteca estándar: QGIS 4
    espera un QIODevice en el cuerpo y con un QByteArray no envía nada.
    """
    from geosian.core.client import GeosianClient
    from geosian.core.http import QgisTransport

    with FakeGeosian() as fake:
        cliente = GeosianClient(fake.url, QgisTransport())
        resultado = cliente.login("tecnico@ejemplo.com", "secreto")

        assert resultado["api_token"] == "tok-de-prueba"
        assert cliente.token == "tok-de-prueba"
        assert cliente.jwt == "jwt-de-prueba"


def test_las_lecturas_no_se_sirven_de_la_cache_de_qt(app):
    """Dos lecturas seguidas tienen que llegar las dos al servidor.

    QgsBlockingNetworkRequest pide con PreferCache si no se le dice otra cosa,
    y entonces el aviso del WebSocket refresca con datos viejos.
    """
    from geosian.core.client import GeosianClient
    from geosian.core.http import QgisTransport

    with FakeGeosian() as fake:
        cliente = GeosianClient(fake.url, QgisTransport(), token="tok-de-prueba")
        cliente.maps()
        cliente.maps()

        assert fake.rutas_pedidas().count("/api/v1/maps/") == 2


def test_conexion_inexistente_da_capa_invalida(app):
    vectorial = QgsVectorLayer(
        "geosian://NoExiste/map/1/layer/2", "x", "geosian"
    )
    assert not vectorial.isValid()


def test_uri_mal_formada_da_capa_invalida(app):
    vectorial = QgsVectorLayer("geosian://Prod/mal", "x", "geosian")
    assert not vectorial.isValid()


def test_credencial_mala_no_tumba_qgis(app):
    """Un token que no vale deja la capa inválida, no revienta el proceso."""
    with FakeGeosian() as fake:
        connections.save_connection("Mala", fake.url, "x@y.z")
        connections.set_session("Mala", "token-que-no-vale")
        try:
            vectorial = QgsVectorLayer(
                "geosian://Mala/map/4/layer/11?geometry_type=points",
                "x",
                "geosian",
            )
            assert not vectorial.isValid()
        finally:
            connections.remove_connection("Mala")


# ----------------------------------------------------------------------
# Login con doble factor, por la pila de red de QGIS
# ----------------------------------------------------------------------


def test_login_con_doble_factor_por_la_red_de_qgis(app):
    from geosian.core.client import GeosianClient
    from geosian.core.http import QgisTransport

    with FakeGeosian() as fake:
        cliente = GeosianClient(fake.url, QgisTransport())
        resultado = cliente.login("doble@ejemplo.com", "secreto")
        assert resultado["mfa_required"]

        cliente.verify_2fa(resultado["mfa_token"], "123456")
        assert cliente.token == "tok-de-prueba"
        assert cliente.jwt == "jwt-de-prueba"


# ----------------------------------------------------------------------
# Capas grandes: por zona
# ----------------------------------------------------------------------


@pytest.fixture
def capa_grande(servidor, monkeypatch):
    """La misma capa, tratada como si pasara del umbral de capa grande."""
    from geosian.provider import provider as modulo

    monkeypatch.setattr(modulo, "LARGE_LAYER", 2)
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points"
    vectorial = QgsVectorLayer(uri, "Arbolado", "geosian")
    assert vectorial.isValid(), vectorial.dataProvider().error()
    return vectorial


def _pedidas_por_zona(servidor):
    return [
        consulta
        for ruta, consulta in servidor.peticiones
        if ruta == "/api/v1/geodata/paginated/" and "ids" not in consulta
    ]


def test_capa_grande_pide_solo_la_zona(capa_grande, servidor):
    proveedor = capa_grande.dataProvider()
    assert proveedor.by_zone
    assert capa_grande.featureCount() == 3  # de los metadatos, sin descargar

    recuadro = QgsRectangle(-3.715, 40.405, -3.705, 40.415)
    elementos = list(capa_grande.getFeatures(QgsFeatureRequest().setFilterRect(recuadro)))
    assert [f.id() for f in elementos] == [1002]
    assert len(_pedidas_por_zona(servidor)) == 1

    # Dentro de lo ya traído no se vuelve a la red.
    dentro = QgsRectangle(-3.712, 40.408, -3.708, 40.412)
    list(capa_grande.getFeatures(QgsFeatureRequest().setFilterRect(dentro)))
    assert len(_pedidas_por_zona(servidor)) == 1


def test_capa_grande_sin_recuadro_carga_hasta_el_tope_y_avisa(capa_grande, servidor, monkeypatch):
    """La tabla de atributos pide la capa sin recuadro: los primeros TABLE_CAP."""
    from geosian.provider import provider as modulo

    monkeypatch.setattr(modulo, "TABLE_CAP", 2)
    monkeypatch.setattr(modulo, "PAGE_SIZE", 2)
    proveedor = capa_grande.dataProvider()
    avisos = []
    monkeypatch.setattr(proveedor, "log_warning", avisos.append)
    proveedor._feature_count = 10  # más que el tope

    elementos = list(capa_grande.getFeatures())
    assert elementos  # ya no sale vacía
    # Ni una zona pedida: es una descarga por páginas, sin recuadro.
    assert all("ids" not in c and c.get("page") for c in _pedidas_por_zona(servidor))
    assert any("la tabla muestra los primeros" in a for a in avisos)


def test_la_tabla_de_una_capa_grande_pide_sin_geometria(capa_grande, servidor):
    """La tabla no pinta formas: se piden solo los atributos (``no_geometry``)."""
    servidor.peticiones.clear()
    elementos = list(capa_grande.getFeatures())
    assert len(elementos) == 3
    assert all(c.get("no_geometry") == ["true"] for c in _pedidas_por_zona(servidor))

    # «Ir al elemento» desde la tabla necesita su forma: se vuelve a pedir ese.
    servidor.peticiones.clear()
    [uno] = list(capa_grande.getFeatures(QgsFeatureRequest(1002)))
    assert not uno.geometry().isNull()
    assert [c["ids"] for r, c in servidor.peticiones if r == "/api/v1/geodata/paginated/"] == [["1002"]]

    # Lo que no necesita forma no vuelve a la red.
    servidor.peticiones.clear()
    peticion = QgsFeatureRequest(1001).setFlags(QgsFeatureRequest.Flag.NoGeometry)
    assert len(list(capa_grande.getFeatures(peticion))) == 1
    assert servidor.peticiones == []


def test_la_tabla_de_una_capa_grande_no_congela_qgis(capa_grande, monkeypatch):
    """QGIS carga la tabla de atributos en el hilo de la ventana: cada página es ~1 s
    congelado. Con 1 M de árboles (Nueva York) eran 10 páginas y 15 s; ahora una."""
    proveedor = capa_grande.dataProvider()
    proveedor._feature_count = 1_000_000
    llamadas = []

    def pagina_llena(layer_id, page=1, page_size=5000, **kwargs):
        llamadas.append(page)
        return {"features": [
            {"type": "Feature", "geometry": None, "properties": {"id": page * page_size + i}}
            for i in range(page_size)
        ]}

    monkeypatch.setattr(proveedor._client, "geodata_paginated", pagina_llena)
    list(capa_grande.getFeatures())
    assert llamadas == [1]


def test_la_tabla_recortada_se_avisa_en_la_barra(capa_grande, monkeypatch):
    """Con 5.000 de un millón, el aviso no puede quedarse en el registro de mensajes."""
    import qgis.utils
    from qgis.PyQt.QtCore import QCoreApplication

    from geosian.provider import provider as modulo

    class Barra:
        def __init__(self):
            self.avisos = []

        def pushWarning(self, titulo, texto):
            self.avisos.append(texto)

    class Iface:
        barra = Barra()

        def messageBar(self):
            return self.barra

    QCoreApplication.processEvents()  # lo que dejó encolado otra prueba
    iface = Iface()
    monkeypatch.setattr(qgis.utils, "iface", iface)
    monkeypatch.setattr(modulo, "TABLE_CAP", 2)
    monkeypatch.setattr(modulo, "PAGE_SIZE", 2)
    proveedor = capa_grande.dataProvider()
    proveedor._feature_count = 1_000_000
    list(capa_grande.getFeatures())
    proveedor.reloadData()
    list(capa_grande.getFeatures())
    assert iface.barra.avisos == []  # al volver al bucle de la ventana, no dentro de la carga
    QCoreApplication.processEvents()
    [aviso] = iface.barra.avisos  # una vez por capa, no en cada recarga
    assert "los primeros" in aviso


def test_capa_grande_sugiere_escala(capa_grande):
    escala = capa_grande.dataProvider().suggested_min_scale()
    assert escala > 0
    assert str(escala)[0] in "125" and set(str(escala)[1:]) <= {"0"}


# ----------------------------------------------------------------------
# Vistas de GCC
# ----------------------------------------------------------------------


def test_vista_filtra_como_la_web(servidor):
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points&view=7"
    vectorial = QgsVectorLayer(uri, "Tilos", "geosian")
    assert vectorial.isValid(), vectorial.dataProvider().error()

    assert [f["codigo"] for f in vectorial.getFeatures()] == ["A-002"]
    assert vectorial.featureCount() == 1
    assert vectorial.dataProvider().view["name"] == "Tilos"
    # Como la web: el filtro viaja en attr__, no en view_ids.
    consultas = [c for r, c in servidor.peticiones if r == "/api/v1/geodata/paginated/"]
    assert consultas and all(c.get("attr__especie") == ["Tilia platyphyllos"] for c in consultas)
    assert not any("view_ids" in c for c in consultas)


# ----------------------------------------------------------------------
# Simbología
# ----------------------------------------------------------------------


def test_el_estilo_del_esquema_pinta_cada_especie(capa):
    from qgis.core import QgsRenderContext

    from geosian.core import symbology

    proveedor = capa.dataProvider()
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    renderizador, avisos = symbology.base_renderer(proveedor.schema, "points", resolver)
    assert avisos == []
    capa.setRenderer(renderizador)

    contexto = QgsRenderContext()
    contexto.expressionContext().appendScopes(
        __import__("qgis.core", fromlist=["QgsExpressionContextUtils"])
        .QgsExpressionContextUtils.globalProjectLayerScopes(capa)
    )
    renderizador.startRender(contexto, capa.fields())
    try:
        colores = {}
        for elemento in capa.getFeatures():
            contexto.expressionContext().setFeature(elemento)
            simbolos = renderizador.symbolsForFeature(elemento, contexto)
            colores[elemento["especie"]] = simbolos[0].color().name()
    finally:
        renderizador.stopRender(contexto)

    assert colores["Tilia platyphyllos"] == "#00ff00"
    assert colores["Platanus x hispanica"] == "#808080"


def test_varios_get_a_la_vez_por_la_red_de_qgis(app):
    from geosian.core.http import QgisTransport, Response

    with FakeGeosian() as fake:
        urls = [f"{fake.url}/api/v1/maps/", f"{fake.url}/api/v1/no-existe/"]
        respuestas = QgisTransport().get_many(
            urls, {"Authorization": "Token tok-de-prueba"}
        )
    assert all(isinstance(r, Response) for r in respuestas)
    assert [r.status for r in respuestas] == [200, 404]
    assert respuestas[0].json()[0]["id"] == 4


def test_la_extension_de_una_vista_es_la_de_lo_filtrado(servidor):
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points&view=7"
    vectorial = QgsVectorLayer(uri, "Tilos", "geosian")
    extension = vectorial.extent()
    # Solo el 1002, en (-3.71, 40.41); la capa entera llega a -3.72.
    assert round(extension.xMinimum(), 2) == -3.71
    assert round(extension.xMaximum(), 2) == -3.71


def test_capa_grande_no_pide_un_recuadro_en_metros(capa_grande, servidor):
    # Lo que llega cuando QGIS no puede transformar la vista: metros de 3857.
    en_metros = QgsRectangle(-8236028.0, 4976711.0, -8235000.0, 4977000.0)
    assert list(capa_grande.getFeatures(QgsFeatureRequest().setFilterRect(en_metros))) == []
    assert _pedidas_por_zona(servidor) == []


def test_el_punto_crece_con_la_escala_entre_sus_topes(app):
    from qgis.core import QgsExpression, QgsExpressionContext, QgsExpressionContextScope

    from geosian.core import symbology

    simbolo = symbology.make_symbol("point", (1, 2, 3, 230))
    capa = simbolo.symbolLayer(0)
    expresion = capa.dataDefinedProperties().property(capa.PropertySize).expressionString()

    def tamaño(escala):
        contexto = QgsExpressionContext()
        ambito = QgsExpressionContextScope()
        ambito.setVariable("map_scale", escala)
        contexto.appendScope(ambito)
        return QgsExpression(expresion).evaluate(contexto)

    assert tamaño(500000) == symbology.POINT_MIN_PX  # de lejos, el mínimo
    assert tamaño(500) == symbology.POINT_MAX_PX  # de cerca, el máximo
    assert symbology.POINT_MIN_PX < tamaño(6000) < symbology.POINT_MAX_PX
    # La leyenda usa el tamaño fijo, que es el máximo en píxeles.
    assert capa.size() == symbology.POINT_MAX_PX


def test_regla_sobre_un_campo_que_no_existe_deja_el_color_por_defecto(capa):
    from qgis.core import QgsSingleSymbolRenderer

    from geosian.core import symbology

    proveedor = capa.dataProvider()
    esquema = {"styles": {"colors": [
        {"attribute": "green_areas.status", "allowed_values": {"1": "#FF0000"}}
    ]}}
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    renderizador, avisos = symbology.base_renderer(esquema, "points", resolver)
    assert isinstance(renderizador, QgsSingleSymbolRenderer)
    assert len(avisos) == 1


def test_vista_con_icono_tiñe_el_icono_por_categoria(capa, tmp_path):
    from qgis.core import QgsSvgMarkerSymbolLayer

    from geosian.core import symbology

    svg = tmp_path / "fa-FaTree.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" fill="param(fill) #000000">'
        '<path d="M0 0h10v10z"/></svg>'
    )
    config = {
        "visualization": "icon",
        "icon": {"defaultIcon": {"lib": "fa", "name": "FaTree"}, "size": 24, "colored": True},
        "color": {"mode": "categorized", "attribute": "especie",
                  "categories": {"Tilia platyphyllos": {"color": [0, 128, 0, 230]}},
                  "default": {"color": [158, 158, 158, 230]}},
    }
    proveedor = capa.dataProvider()
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    renderizador, avisos = symbology.view_renderer(
        config, "points", proveedor.schema, resolver, iconos=lambda lib, nombre: str(svg)
    )
    assert avisos == []
    reglas = renderizador.rootRule().children()
    simbolo = reglas[0].symbol()
    # Halo blanco detrás y el icono teñido del color de la categoría.
    assert [type(c) for c in simbolo.symbolLayers()] == [QgsSvgMarkerSymbolLayer] * 2
    assert simbolo.symbolLayer(0).fillColor().name() == "#ffffff"
    assert simbolo.symbolLayer(1).fillColor().name() == "#008000"


def test_vista_con_icono_sin_red_pinta_circulos(capa):
    from geosian.core import symbology

    config = {"visualization": "icon", "icon": {"defaultIcon": {"lib": "fa", "name": "FaTree"}},
              "color": {"mode": "categorized", "attribute": "especie", "categories": {}}}
    proveedor = capa.dataProvider()
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    _, avisos = symbology.view_renderer(
        config, "points", proveedor.schema, resolver, iconos=lambda lib, nombre: None
    )
    assert any("FaTree" in a for a in avisos)


def test_ruta_con_punto_no_se_queda_con_el_ultimo_tramo(capa):
    """Como la web: «x.especie» no es «especie» si no hay objeto «x»."""
    from geosian.core import symbology

    proveedor = capa.dataProvider()
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    assert resolver("especie") == "especie"
    assert resolver("surface_type.especie") is None


# ----------------------------------------------------------------------
# Información adicional (partes)
# ----------------------------------------------------------------------

@pytest.fixture
def partes(servidor):
    uri = f"geosian://{CONEXION}/map/4/layer/11/info/parte_poda?geometry_type=points"
    tabla = QgsVectorLayer(uri, "Parte de poda", "geosian")
    assert tabla.isValid(), tabla.dataProvider().error()
    return tabla


def test_los_partes_son_una_tabla_con_los_campos_de_su_esquema(partes):
    assert partes.wkbType() == QgsWkbTypes.NoGeometry
    nombres = partes.fields().names()
    for campo in ("id", "geodata_id", "usuario", "created_at", "labor", "horas"):
        assert campo in nombres
    assert "pictures" not in nombres
    assert partes.fields().field("labor").alias() == "Labor"


def test_los_partes_de_un_elemento_se_piden_solo_para_el(partes, servidor):
    servidor.peticiones.clear()
    peticion = QgsFeatureRequest().setFilterExpression('"geodata_id" = 1001')
    leidos = list(partes.getFeatures(peticion))

    assert sorted(f["id"] for f in leidos) == [501, 502]
    assert {f["labor"] for f in leidos} == {"Poda", "Aclareo"}
    assert leidos[0]["usuario"] in ("Técnica Uno", "Técnico Dos")
    pedidas = [c for r, c in servidor.peticiones if r == "/api/v1/additional-information/"]
    assert pedidas and all(c.get("geodata_id") == ["1001"] for c in pedidas)
    # Sin orden propio: el del servidor, el más reciente primero, como la web.
    assert all("sort_by" not in c for c in pedidas)


def test_la_tabla_de_partes_sin_filtro_trae_los_de_la_capa(partes):
    assert sorted(f["id"] for f in partes.getFeatures()) == [501, 502, 503]
    assert partes.featureCount() == 3


def test_tipo_de_parte_que_no_existe_da_capa_invalida(servidor):
    uri = f"geosian://{CONEXION}/map/4/layer/11/info/no_existe?geometry_type=points"
    assert not QgsVectorLayer(uri, "x", "geosian").isValid()


# ----------------------------------------------------------------------
# Fotos y adjuntos
# ----------------------------------------------------------------------

def test_fotos_y_ficheros_de_un_elemento(capa, servidor):
    from tests.fake_server import FICHERO_PDF, FOTO_PNG, MINIATURA_PNG

    proveedor = capa.dataProvider()
    elementos = proveedor.media_of(1001)

    # La portada primero, luego el resto de fotos y al final los ficheros.
    assert [(m.kind, m.id) for m in elementos] == [("image", 72), ("image", 71), ("file", 31)]
    # La ficha se pide con enlaces, no con las fotos enteras dentro.
    [consulta] = [c for r, c in servidor.peticiones if r == "/api/v1/geodata/1001/"]
    assert consulta["embed_images"] == ["false"]
    assert elementos[0].data is None
    assert proveedor.media_bytes(elementos[0]) == FOTO_PNG
    assert proveedor.media_bytes(elementos[0], thumb=True) == MINIATURA_PNG
    assert elementos[2].name == "informe.pdf"
    assert proveedor.media_bytes(elementos[2]) == FICHERO_PDF


def test_fotos_de_un_parte_por_enlace(partes, servidor):
    from tests.fake_server import FOTO_PNG

    peticion = QgsFeatureRequest().setFilterExpression('"geodata_id" = 1001')
    list(partes.getFeatures(peticion))
    proveedor = partes.dataProvider()

    [foto] = proveedor.media_of(501)
    assert foto.url == "/api/v1/additional-information/image/88/"
    assert proveedor.media_bytes(foto) == FOTO_PNG
    assert proveedor.media_of(502) == []


# ----------------------------------------------------------------------
# Filtro de la capa («Filtrar…» de QGIS), como los filtros de la web
# ----------------------------------------------------------------------

def _pedidas(servidor):
    return [c for r, c in servidor.peticiones if r == "/api/v1/geodata/paginated/"]


def test_filtro_sencillo_va_al_servidor(capa, servidor):
    servidor.peticiones.clear()
    assert capa.setSubsetString("\"especie\" = 'Tilia platyphyllos'")

    assert [f["id"] for f in capa.getFeatures()] == [1002]
    assert capa.featureCount() == 1
    # Igual que la web: el filtro viaja como attr__ y no se baja la capa entera.
    assert all(c.get("attr__especie") == ["Tilia platyphyllos"] for c in _pedidas(servidor))


def test_filtro_que_la_api_no_entiende_se_aplica_en_qgis(capa, servidor):
    servidor.peticiones.clear()
    assert capa.setSubsetString("\"especie\" = 'Tilia platyphyllos' OR \"altura\" > 10")

    assert sorted(f["id"] for f in capa.getFeatures()) == [1001, 1002]
    assert all("attr__especie" not in c for c in _pedidas(servidor))


def test_parte_traducible_de_un_filtro_compuesto(capa, servidor):
    servidor.peticiones.clear()
    assert capa.setSubsetString(
        "\"especie\" IN ('Platanus x hispanica', 'Tilia platyphyllos') AND \"altura\" > 10"
    )

    assert [f["id"] for f in capa.getFeatures()] == [1001]
    # La parte del IN la filtra el servidor; la de la altura, QGIS.
    [consulta] = _pedidas(servidor)
    assert sorted(consulta["attr__especie"]) == ["Platanus x hispanica", "Tilia platyphyllos"]


def test_filtro_mal_escrito_no_cambia_nada(capa):
    assert not capa.dataProvider().setSubsetString("\"especie\" = = 'x'")
    assert capa.dataProvider().subsetString() == ""
    assert capa.featureCount() == 3


def test_quitar_el_filtro_devuelve_la_capa_entera(capa):
    capa.setSubsetString("\"especie\" = 'Tilia platyphyllos'")
    assert capa.featureCount() == 1
    capa.setSubsetString("")
    assert sorted(f["id"] for f in capa.getFeatures()) == [1001, 1002, 1003]


def test_el_limite_se_aplica_despues_del_filtro(capa):
    # Que no pase el primero de la caché: con el límite antes, no salía ninguno.
    capa.setSubsetString("\"altura\" < 10")
    peticion = QgsFeatureRequest().setLimit(1)
    assert [f["id"] for f in capa.getFeatures(peticion)] == [1002]


def test_el_filtro_se_conserva_al_guardar_y_reabrir_el_proyecto(capa, tmp_path):
    from qgis.core import QgsProject

    proyecto = QgsProject.instance()
    proyecto.clear()
    proyecto.addMapLayer(capa)
    capa.setSubsetString("\"especie\" = 'Tilia platyphyllos'")
    ruta = str(tmp_path / "prueba.qgz")
    assert proyecto.write(ruta)
    proyecto.clear()
    assert proyecto.read(ruta)

    [reabierta] = [c for c in proyecto.mapLayers().values() if c.providerType() == "geosian"]
    assert reabierta.subsetString() == "\"especie\" = 'Tilia platyphyllos'"
    assert [f["id"] for f in reabierta.getFeatures()] == [1002]
    proyecto.clear()


# ----------------------------------------------------------------------
# Errores: ninguno debe colgar QGIS y el mensaje tiene que decir qué pasa
# ----------------------------------------------------------------------

def test_capa_borrada_en_gcc(servidor):
    capa = QgsVectorLayer(f"geosian://{CONEXION}/map/4/layer/999?geometry_type=points", "x", "geosian")
    assert not capa.isValid()
    assert "ya no existe" in capa.dataProvider().error()


def test_capa_sin_permiso(servidor):
    capa = QgsVectorLayer(f"geosian://{CONEXION}/map/5/layer/50?geometry_type=points", "x", "geosian")
    assert not capa.isValid()
    assert "permiso" in capa.dataProvider().error()


def test_sesion_caducada_a_mitad_no_deja_la_capa_vacia_para_siempre(capa, servidor):
    connections.clear_expired()
    connections.set_session(CONEXION, "tok-revocado", "jwt")
    capa.dataProvider().reloadData()

    assert list(capa.getFeatures()) == []
    assert CONEXION in connections.expired()

    # Al volver a entrar, la capa vuelve a pedir sus datos.
    from geosian.gui import sesion

    connections.set_session(CONEXION, "tok-de-prueba", "jwt")
    sesion.repair_layers(CONEXION, [capa])
    assert sorted(f["id"] for f in capa.getFeatures()) == [1001, 1002, 1003]
    connections.clear_expired()


def test_red_caida_no_reintenta_en_cada_peticion(capa, servidor):
    import time

    proveedor = capa.dataProvider()
    servidor.__exit__()  # el servidor deja de contestar
    proveedor.reloadData()

    inicio = time.monotonic()
    assert list(capa.getFeatures()) == []
    # Tras el primer fallo, la capa espera un poco antes de volver a la red: la
    # tabla de atributos y la ficha piden datos sin parar y cada intento congela.
    llamadas = []
    original = proveedor._client._get
    proveedor._client._get = lambda *a, **k: (llamadas.append(a), original(*a, **k))[1]
    for _ in range(5):
        proveedor.reloadData()
        list(capa.getFeatures())
    assert llamadas == []
    assert time.monotonic() - inicio < 5


def test_servidor_que_no_contesta_respeta_el_tiempo_de_espera(app):
    import socket
    import time

    from geosian.core.client import GeosianClient
    from geosian.core.errors import NetworkError
    from geosian.core.http import QgisTransport

    mudo = socket.socket()
    mudo.bind(("127.0.0.1", 0))
    mudo.listen(1)  # acepta conexiones y no contesta nunca
    try:
        cliente = GeosianClient(
            f"http://127.0.0.1:{mudo.getsockname()[1]}", transport=QgisTransport(), timeout=1
        )
        inicio = time.monotonic()
        with pytest.raises(NetworkError):
            cliente.maps()
        assert time.monotonic() - inicio < 5
    finally:
        mudo.close()


def test_capa_que_ya_no_esta_en_el_mapa(servidor):
    # La API contesta a /layer-attributes/ de una capa inexistente con una lista
    # vacía, no con un 404: la capa se abría válida y vacía.
    capa = QgsVectorLayer(f"geosian://{CONEXION}/map/4/layer/777?geometry_type=points", "x", "geosian")
    assert not capa.isValid()
    assert "ya no existe" in capa.dataProvider().error()


def test_capa_de_un_mapa_sin_permiso_aunque_la_api_de_lista_vacia(servidor):
    # Devel con una cuenta que solo ve otro mapa: /layer-attributes/ da [] y el listado
    # de capas del mapa, 403. La capa se abría «válida» y vacía.
    capa = QgsVectorLayer(f"geosian://{CONEXION}/map/5/layer/51?geometry_type=points", "x", "geosian")
    assert not capa.isValid()
    assert "permiso" in capa.dataProvider().error()


def test_con_la_sesion_caducada_abre_vacia_con_los_campos_que_ya_tenia(capa):
    """Reabrir un proyecto días después: la capa no queda «no disponible» (QGIS
    sacaría su diálogo y, al guardar, perdería la configuración de sus campos)."""
    connections.clear_expired()
    campos = capa.fields().names()
    connections.set_session(CONEXION, "tok-caducado", "jwt")
    try:
        reabierta = QgsVectorLayer(capa.source(), "Arbolado", "geosian")
        assert reabierta.isValid(), reabierta.dataProvider().error()
        assert reabierta.fields().names() == campos
        assert reabierta.featureCount() == 0
        assert list(reabierta.getFeatures()) == []
        assert CONEXION in connections.expired()

        # Al volver a entrar, recargar la recupera con sus datos.
        connections.set_session(CONEXION, "tok-de-prueba", "jwt-de-prueba")
        reabierta.reload()
        assert reabierta.featureCount() == 3
        assert len(list(reabierta.getFeatures())) == 3
    finally:
        connections.set_session(CONEXION, "tok-de-prueba", "jwt-de-prueba")
        connections.clear_expired()


def test_sin_definicion_guardada_sigue_sin_estar_disponible(servidor):
    connections.set_session(CONEXION, "tok-caducado", "jwt")
    try:
        capa = QgsVectorLayer(
            f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points", "Arbolado", "geosian"
        )
        assert not capa.isValid()
    finally:
        connections.set_session(CONEXION, "tok-de-prueba", "jwt-de-prueba")
        connections.clear_expired()


def test_quitar_la_conexion_borra_sus_definiciones(capa):
    from geosian.core import definitions

    uri = capa.dataProvider().layer_uri
    base = connections.client_for(CONEXION).base_url
    assert definitions.load(CONEXION, base, uri) is not None
    definitions.forget(CONEXION)
    assert definitions.load(CONEXION, base, uri) is None


def test_filtros_de_partes_y_fechas_llegan_a_la_api(servidor):
    """Como el panel de filtros de la web: elementos con partes que cumplen algo y
    partes entre dos fechas. Lo resuelve el servidor; el recuento se sabe al bajar."""
    uri = (
        f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points"
        "&parte=parte_poda__labor%3DPoda&date_from=2026-01-01&date_to=2026-03-31&most_recent=1"
    )
    capa = QgsVectorLayer(uri, "Arbolado", "geosian")
    assert capa.isValid(), capa.dataProvider().error()
    servidor.peticiones.clear()
    list(capa.getFeatures())
    [consulta] = [c for r, c in servidor.peticiones if r == "/api/v1/geodata/paginated/"][:1]
    assert consulta["attr__parte_poda__labor"] == ["Poda"]
    assert consulta["date_from"] == ["2026-01-01"]
    assert consulta["date_to"] == ["2026-03-31"]
    assert consulta["most_recent"] == ["true"]
    assert consulta["timezone"][0]


def test_un_filtro_de_un_parte_que_no_existe_avisa(servidor):
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points&parte=no_existe__x%3D1"
    capa = QgsVectorLayer(uri, "Arbolado", "geosian")
    assert not capa.isValid()
    assert "no_existe" in capa.dataProvider().error()


class _BarraFalsa:
    def __init__(self):
        self.avisos = []

    def pushWarning(self, titulo, texto):
        self.avisos.append(texto)


class _IfaceFalso:
    def __init__(self):
        self.barra = _BarraFalsa()

    def messageBar(self):
        return self.barra


def test_recargar_sin_red_conserva_lo_que_habia(capa, monkeypatch):
    """El tiempo real o «Recargar» con la red caída: la capa no se queda vacía."""
    from geosian.core.errors import NetworkError

    assert len(list(capa.getFeatures())) == 3
    proveedor = capa.dataProvider()
    original = proveedor._client.geodata_paginated

    def sin_red(*args, **kwargs):
        raise NetworkError("Host desconocido")

    monkeypatch.setattr(proveedor._client, "geodata_paginated", sin_red)
    try:
        proveedor.reloadData()
        assert len(list(capa.getFeatures())) == 3
        assert connections.is_offline(CONEXION)

        # Vuelta la red y pasada la pausa, se recarga de verdad.
        monkeypatch.setattr(proveedor._client, "geodata_paginated", original)
        connections._sin_red.clear()
        assert len(list(capa.getFeatures())) == 3
        assert proveedor._loaded
    finally:
        connections._sin_red.clear()


def test_sin_red_se_avisa_en_la_barra_una_vez(capa, monkeypatch):
    import qgis.utils
    from qgis.PyQt.QtCore import QCoreApplication

    from geosian.core.errors import NetworkError

    QCoreApplication.processEvents()  # lo que dejó encolado otra prueba
    iface = _IfaceFalso()
    monkeypatch.setattr(qgis.utils, "iface", iface)
    proveedor = capa.dataProvider()

    def sin_red(*args, **kwargs):
        raise NetworkError("Host desconocido")

    monkeypatch.setattr(proveedor._client, "geodata_paginated", sin_red)
    try:
        proveedor.reloadData()
        list(capa.getFeatures())
        proveedor.reloadData()
        list(capa.getFeatures())
        QCoreApplication.processEvents()
        [aviso] = iface.barra.avisos
        assert "sin conexión" in aviso.lower()
    finally:
        connections._sin_red.clear()


def test_una_seleccion_multiple_con_un_valor_suelto_llega_como_lista(capa):
    """En Melilla, «Zona» y «Barrio» son de selección múltiple, pero muchos elementos
    guardan un texto suelto («Zona Victoria»). QGIS lo pintaba letra a letra, con comas."""
    proveedor = capa.dataProvider()
    idx = capa.fields().indexOf("operacion")
    valores = proveedor._attributes_from({"operacion": "Poda"}, 1)
    assert valores[idx] == ["Poda"]
    assert proveedor._attributes_from({"operacion": ["Poda", "Tala"]}, 1)[idx] == ["Poda", "Tala"]
    assert proveedor._attributes_from({"operacion": ""}, 1)[idx] is None
    assert proveedor._attributes_from({}, 1)[idx] is None


def test_la_seleccion_multiple_usa_el_editor_de_listas(capa):
    """Con el editor de texto por omisión, QGIS 4 pintaba la lista como «Z, ,, , ,,»."""
    lad.apply_editor_config(capa, capa.dataProvider().schema)
    assert capa.editorWidgetSetup(capa.fields().indexOf("operacion")).type() == "List"


def _svg(tmp_path):
    svg = tmp_path / "fa-FaTree.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" fill="param(fill) #000000">'
        '<path d="M0 0h10v10z"/></svg>'
    )
    return str(svg)


def test_el_modo_de_carga_como_la_web():
    """``getLayerLoadMode`` de la web: decide si la capa va por teselas o en GeoJSON."""
    from geosian.core import styles

    grande, pequeña = {"feature_count": 6000}, {"feature_count": 4000}
    assert styles.load_mode({"mode": "mvt"}, pequeña, {}) == "mvt"
    assert styles.load_mode({"mode": "geojson"}, grande, {}) == "geojson"
    assert styles.load_mode({"mode": "auto", "auto_threshold": 5000}, grande, {}) == "mvt"
    assert styles.load_mode({"mode": "auto"}, pequeña, {}) == "geojson"
    assert styles.load_mode({"mode": "manual"}, grande, {"lod": {"mode": "mvt"}}) == "mvt"
    assert styles.load_mode({"mode": "manual"}, grande, {}) == "geojson"
    # Un servidor que no da la configuración: la de la web por omisión.
    assert styles.load_mode(None, grande, {}) == "geojson"


@pytest.mark.parametrize("modo, teselas, en_metros", [
    ("categorized", True, True),     # por teselas: metros, entre max(8, sizeMin/2) y size px
    ("single", True, True),
    ("categorized", False, False),   # capa en GeoJSON: size px, entre sizeMin y sizeMax
    ("graduated", True, False),      # graduada: la web nunca la lleva por teselas
    ("rule_based", True, False),
])
def test_el_tamaño_del_icono_sigue_el_camino_de_la_web(capa, tmp_path, modo, teselas, en_metros):
    from qgis.core import QgsRenderContext, QgsSymbolLayer

    from geosian.core import symbology

    config = {"mode": modo, "visualization": "icon",
              "icon": {"defaultIcon": {"lib": "fa", "name": "FaTree"}, "size": 60, "sizeMin": 20,
                       "sizeMax": 40},
              "color": {"mode": modo, "value": [1, 2, 3]}}
    proveedor = capa.dataProvider()
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    renderizador, _ = symbology.view_renderer(
        config, "points", proveedor.schema, resolver, iconos=lambda lib, nombre: _svg(tmp_path),
        teselas=teselas)
    simbolo = renderizador.symbols(QgsRenderContext())[0]
    halo, icono = simbolo.symbolLayers()
    calculado = icono.dataDefinedProperties().property(QgsSymbolLayer.PropertySize)
    if en_metros:
        assert calculado.isActive()
        assert calculado.expressionString().startswith("(clamp(10.0, 60.0 /")
        assert halo.fillColor().alpha() == 235
    else:
        # Fijo: 60 px acotado a [20, 40]; el halo, un 18 % mayor y con el blanco de esa vía.
        assert not calculado.isActive()
        assert icono.size() == 40
        assert round(halo.size(), 2) == round(40 * 1.18, 2)
        assert halo.fillColor().alpha() == 230


def test_vista_de_iconos_sin_icono_no_pinta_nada(capa):
    """Sin ``defaultIcon`` la web no dibuja la vista; antes salían círculos."""
    from qgis.core import QgsNullSymbolRenderer

    from geosian.core import symbology

    config = {"mode": "categorized", "visualization": "icon", "icon": {"defaultIcon": None},
              "color": {"mode": "categorized", "attribute": "especie", "categories": {}}}
    proveedor = capa.dataProvider()
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    renderizador, avisos = symbology.view_renderer(config, "points", proveedor.schema, resolver)
    assert isinstance(renderizador, QgsNullSymbolRenderer)
    assert any("no tiene icono" in a for a in avisos)


@pytest.mark.parametrize("config, esperado", [
    ({"mode": "mvt", "auto_threshold": 5000}, True),
    ({"mode": "geojson", "auto_threshold": 5000}, False),
    ({"mode": "auto", "auto_threshold": 2}, True),      # la capa de prueba tiene 3
    ({"mode": "auto", "auto_threshold": 5000}, False),
    (None, False),                                     # un servidor que no lo da
])
def test_el_panel_sabe_si_la_web_lleva_la_capa_por_teselas(servidor, config, esperado):
    from geosian.gui import browser_dock

    servidor.poner_tile_config(config)
    vectorial = QgsVectorLayer(f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points", "A", "geosian")
    vectorial.dataProvider()._client.forget_layers()
    assert browser_dock._por_teselas(vectorial.dataProvider()) is esperado
    assert any(c.get("include_tile_config") == ["true"]
               for r, c in servidor.peticiones if r == "/api/v1/maps/4/layers/")
