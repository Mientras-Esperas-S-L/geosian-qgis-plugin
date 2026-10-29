"""La contraseña provisional se cambia desde QGIS, como en la web.

Una cuenta recién dada de alta, o reseteada por un administrador, entra con una contraseña
que conoce quien la puso. La web obliga a cambiarla al primer acceso; el complemento no lo
hacía, y quien solo usa QGIS se quedaba con ella para siempre.
"""

import json

import pytest

from geosian.core.client import GeosianClient
from geosian.core.errors import ApiError
from geosian.core.http import Response, Transport

from .fake_server import FakeGeosian

qgis_core = pytest.importorskip("qgis.core")


class TransporteFalso(Transport):
    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.llamadas = []

    def request(self, method, url, headers=None, body=None, timeout=30):
        self.llamadas.append({"url": url, "headers": headers or {}, "body": json.loads(body) if body else None})
        for patron, (status, datos) in self.respuestas.items():
            if patron in url:
                return Response(status, json.dumps(datos).encode("utf-8"))
        return Response(200, b"{}")


def test_el_login_avisa_de_que_hay_que_cambiarla():
    transporte = TransporteFalso(
        {"/users/login/": (202, {"api_token": "tok", "jwt_token": "jwt", "requires_password_change": True})}
    )
    cliente = GeosianClient("https://api.ejemplo.com", transporte)
    cliente.login("a@b.c", "provisional")

    assert cliente.requiere_cambio_contrasena


def test_un_login_normal_no_pide_cambiarla():
    transporte = TransporteFalso({"/users/login/": (202, {"api_token": "tok", "jwt_token": "jwt"})})
    cliente = GeosianClient("https://api.ejemplo.com", transporte)
    cliente.login("a@b.c", "secreto")

    assert not cliente.requiere_cambio_contrasena


def test_cambiarla_usa_la_ruta_de_la_web_y_se_queda_con_el_token_nuevo():
    transporte = TransporteFalso(
        {"/user-management/change-own-password/": (200, {"success": True, "api_token": "nuevo", "jwt_token": "jwt-nuevo"})}
    )
    cliente = GeosianClient("https://api.ejemplo.com", transporte, token="viejo")
    cliente.requiere_cambio_contrasena = True

    cliente.cambiar_contrasena("provisional", "Una-nueva-larga-1")

    llamada = transporte.llamadas[0]
    assert llamada["url"].endswith("/api/v1/user-management/change-own-password/")
    assert llamada["headers"]["Authorization"] == "Token viejo"
    assert llamada["body"] == {"current_password": "provisional", "new_password": "Una-nueva-larga-1"}
    # El cambio revoca el token anterior: sin el nuevo, lo siguiente daría 401.
    assert cliente.token == "nuevo"
    assert cliente.jwt == "jwt-nuevo"
    assert not cliente.requiere_cambio_contrasena


def test_el_rechazo_por_campo_llega_legible():
    transporte = TransporteFalso(
        {
            "/change-own-password/": (
                400,
                {"new_password": ["Debe tener al menos 12 caracteres.", "No puede repetir una anterior."]},
            )
        }
    )
    cliente = GeosianClient("https://api.ejemplo.com", transporte, token="tok")

    with pytest.raises(ApiError) as error:
        cliente.cambiar_contrasena("provisional", "corta")

    assert error.value.args[0] == "Debe tener al menos 12 caracteres. No puede repetir una anterior."


def _exec_que_escribe(nueva, repetida=None):
    """Sustituye al exec() del diálogo: escribe, pulsa Cambiar y dice si se aceptó."""

    def exec_(dialogo):
        dialogo.txt_nueva.setText(nueva)
        dialogo.txt_repetida.setText(nueva if repetida is None else repetida)
        dialogo._cambiar()
        exec_.mensaje = dialogo.lbl_estado.text()
        return dialogo.result() == dialogo.DialogCode.Accepted

    exec_.mensaje = None
    return exec_


def _dialogo_relleno(servidor):
    from geosian.gui.connection_dialog import ConnectionDialog

    dialogo = ConnectionDialog()
    dialogo.txt_nombre.setText("Provisional")
    dialogo.txt_url.setText(servidor.url)
    dialogo.txt_email.setText("provisional@ejemplo.com")
    dialogo.txt_password.setText("provisional")
    return dialogo


@pytest.fixture
def sin_conexion_guardada():
    from geosian.core import connections

    yield
    connections.remove_connection("Provisional")


def test_al_conectar_con_la_provisional_se_cambia_y_se_guarda_el_token_nuevo(app_gui, monkeypatch, sin_conexion_guardada):
    from geosian.core import connections
    from geosian.gui import connection_dialog

    exec_ = _exec_que_escribe("Una-nueva-larga-1")
    monkeypatch.setattr(connection_dialog.CambioContrasenaDialog, "exec", exec_)

    with FakeGeosian() as servidor:
        dialogo = _dialogo_relleno(servidor)
        dialogo._conectar()

        assert dialogo.connection_name == "Provisional"
        assert connections.get_credentials("Provisional")["token"] == "tok-nuevo"
        cambio = [d for ruta, d in servidor.peticiones if ruta.endswith("/change-own-password/")]
        assert cambio == [{"current_password": "provisional", "new_password": "Una-nueva-larga-1"}]


def test_si_el_servidor_la_rechaza_se_ve_el_motivo_y_no_se_entra(app_gui, monkeypatch, sin_conexion_guardada):
    from geosian.core import connections
    from geosian.gui import connection_dialog

    exec_ = _exec_que_escribe("corta-123")
    monkeypatch.setattr(connection_dialog.CambioContrasenaDialog, "exec", exec_)

    with FakeGeosian() as servidor:
        dialogo = _dialogo_relleno(servidor)
        dialogo._conectar()

    assert exec_.mensaje == "La contraseña debe tener al menos 12 caracteres."
    assert dialogo.connection_name is None
    assert "contraseña provisional" in dialogo.lbl_estado.text()
    assert not connections.get_connection("Provisional")


def test_si_no_coinciden_no_se_manda_nada(app_gui, monkeypatch, sin_conexion_guardada):
    from geosian.gui import connection_dialog

    exec_ = _exec_que_escribe("Una-nueva-larga-1", repetida="Otra-distinta-22")
    monkeypatch.setattr(connection_dialog.CambioContrasenaDialog, "exec", exec_)

    with FakeGeosian() as servidor:
        dialogo = _dialogo_relleno(servidor)
        dialogo._conectar()
        assert not [r for r, _ in servidor.peticiones if r.endswith("/change-own-password/")]

    assert exec_.mensaje == "Las dos contraseñas no coinciden."
    assert dialogo.connection_name is None


def test_un_usuario_normal_no_ve_el_cambio(app_gui, monkeypatch):
    from geosian.core import connections
    from geosian.gui import connection_dialog

    def no_deberia_abrirse(_dialogo):
        raise AssertionError("el cambio de contraseña no debía abrirse")

    monkeypatch.setattr(connection_dialog.CambioContrasenaDialog, "exec", no_deberia_abrirse)

    with FakeGeosian() as servidor:
        dialogo = _dialogo_relleno(servidor)
        dialogo.txt_email.setText("tecnico@ejemplo.com")
        dialogo._conectar()

    assert dialogo.connection_name == "Provisional"
    connections.remove_connection("Provisional")
