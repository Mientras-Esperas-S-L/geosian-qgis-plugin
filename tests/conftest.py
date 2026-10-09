"""Configuración común de las pruebas.

Solo puede haber **una** QgsApplication por proceso: crear una segunda tumba el
intérprete con un volcado, no con una excepción. Por eso vive aquí, con alcance
de sesión, y todos los módulos de prueba la comparten.

Se crea con interfaz gráfica activada aunque no se vea nada (``offscreen``),
porque las pruebas de la interfaz construyen widgets de verdad.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsApplication  # noqa: E402


@pytest.fixture(scope="session")
def app():
    QgsApplication.setPrefixPath("/usr", True)
    aplicacion = QgsApplication([], True)
    aplicacion.initQgis()
    # Los tipos de campo de QGIS (texto, lista…). La aplicación de QGIS los
    # registra sola; aquí no, y una ficha con un campo sin tipo se cae.
    from qgis.gui import QgsGui

    QgsGui.editorWidgetRegistry().initEditors()

    from geosian.provider.metadata import register_provider

    register_provider()

    yield aplicacion
    aplicacion.exitQgis()


@pytest.fixture(scope="session")
def app_gui(app):
    """Alias: las pruebas de interfaz necesitan lo mismo que las demás."""
    return app
