"""El paquete con el servidor fijado (`make package SERVIDOR=...`).

Se hace para que un técnico pruebe en devel sin poder equivocarse de servidor. Lo que tiene
que cumplir: se conecta siempre al fijado, el diálogo no deja cambiarlo, y una conexión de
una instalación anterior contra otro servidor no se lleva su token al fijado.
"""

import os
import shutil
import subprocess
import zipfile

import pytest

qgis_core = pytest.importorskip("qgis.core")

from geosian.core import connections, servidor

DEVEL = "https://api.devel.greencitycontrol.com"
PRODUCCION = "https://api.greencitycontrol.com"


@pytest.fixture
def fijado_en_devel(monkeypatch):
    monkeypatch.setattr(servidor, "SERVIDOR_FIJO", DEVEL)
    yield
    connections.remove_connection("Antigua")


def test_sin_servidor_fijado_vale_cualquiera():
    assert servidor.fijo() is None
    assert servidor.es_el_fijo(PRODUCCION)


def test_una_conexion_a_otro_servidor_va_al_fijado_y_sin_su_token(app, fijado_en_devel):
    connections.save_connection("Antigua", PRODUCCION, "tecnico@talher.es")
    connections.set_session("Antigua", "token-de-produccion", "jwt-de-produccion")

    cliente = connections.client_for("Antigua")

    assert cliente.base_url.rstrip("/") == DEVEL
    assert not cliente.token
    assert not getattr(cliente, "jwt", None)


def test_el_dialogo_no_ensena_la_casilla_del_servidor_fijado(app_gui, fijado_en_devel):
    from qgis.PyQt.QtWidgets import QLabel

    from geosian.gui.connection_dialog import ConnectionDialog

    dialogo = ConnectionDialog()

    assert dialogo.txt_url.text() == DEVEL
    assert not dialogo.txt_url.isVisibleTo(dialogo)
    assert "Servidor" not in [etiqueta.text() for etiqueta in dialogo.findChildren(QLabel)]
    assert "DEVEL" in dialogo.windowTitle()


def test_sin_servidor_fijado_la_casilla_se_ve(app_gui):
    from geosian.gui.connection_dialog import ConnectionDialog

    dialogo = ConnectionDialog()

    assert dialogo.txt_url.isVisibleTo(dialogo)
    assert not dialogo.txt_url.isReadOnly()


def test_el_de_produccion_no_lleva_marca_de_pruebas(monkeypatch):
    monkeypatch.setattr(servidor, "SERVIDOR_FIJO", PRODUCCION)
    assert servidor.entorno() is None
    assert servidor.titulo() == "GreenCityControl"


# La imagen de QGIS del CI no trae make, git ni zip; el paquete lo comprueba el trabajo
# "paquete" de .github/workflows/pruebas.yml.
@pytest.mark.skipif(
    not all(shutil.which(p) for p in ("make", "git", "zip")), reason="sin make, git o zip"
)
def test_make_package_escribe_el_servidor_en_el_zip(tmp_path):
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    salida = subprocess.run(
        ["make", "-s", "package", f"SERVIDOR={DEVEL}", f"BUILD={tmp_path}"],
        cwd=raiz, capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()[-1]

    assert salida.endswith("-api-devel-greencitycontrol-com.zip")
    with zipfile.ZipFile(salida) as paquete:
        fuente = paquete.read("geosian/core/servidor.py").decode()
        metadatos = paquete.read("geosian/metadata.txt").decode()
    assert f'SERVIDOR_FIJO = "{DEVEL}"' in fuente
    # En el gestor de complementos se distingue del de producción.
    assert "name=GreenCityControl DEVEL (pruebas)" in metadatos.splitlines()
    # El código fuente no se toca: solo la copia empaquetada.
    with open(os.path.join(raiz, "geosian/core/servidor.py")) as original:
        assert 'SERVIDOR_FIJO = ""' in original.read()
