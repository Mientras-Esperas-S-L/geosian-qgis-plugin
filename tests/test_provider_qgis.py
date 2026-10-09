"""Prueba de punta a punta del proveedor, con QGIS de verdad.

Levanta un servidor que responde como Geosian, registra el proveedor, abre una
capa y comprueba lo que vería el técnico: campos, datos, geometrías, formulario
y valores de los desplegables.

Se ejecuta con el Python que tenga PyQGIS:

    QT_QPA_PLATFORM=offscreen pytest tests/test_provider_qgis.py
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import (  # noqa: E402
    QgsFeatureRequest,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)

from geosian.core import connections, lad  # noqa: E402
from tests.fake_server import FakeGeosian  # noqa: E402

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


def test_desplegable_de_valores_permitidos(capa):
    lad.apply_editor_config(capa, capa.dataProvider().schema)
    idx = capa.fields().indexOf("especie")
    setup = capa.editorWidgetSetup(idx)
    assert setup.type() == "ValueMap"
    valores = [list(d.values())[0] for d in setup.config()["map"]]
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
                f"geosian://Mala/map/4/layer/11?geometry_type=points",
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


def test_capa_grande_sin_recuadro_no_se_descarga_entera(capa_grande, servidor):
    assert list(capa_grande.getFeatures()) == []
    assert _pedidas_por_zona(servidor) == []


def test_capa_grande_sugiere_escala(capa_grande):
    escala = capa_grande.dataProvider().suggested_min_scale()
    assert escala > 0
    assert str(escala)[0] in "125" and set(str(escala)[1:]) <= {"0"}


# ----------------------------------------------------------------------
# Vistas de GCC
# ----------------------------------------------------------------------


def test_vista_filtra_en_el_servidor(servidor):
    uri = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points&view=7"
    vectorial = QgsVectorLayer(uri, "Tilos", "geosian")
    assert vectorial.isValid(), vectorial.dataProvider().error()

    assert [f["codigo"] for f in vectorial.getFeatures()] == ["A-002"]
    assert vectorial.featureCount() == 1
    consultas = [c for r, c in servidor.peticiones if r == "/api/v1/geodata/paginated/"]
    assert all(c.get("view_ids") == ["7"] for c in consultas)


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
