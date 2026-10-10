"""Pruebas del cliente de la API con un transporte de mentira."""

import json

import pytest

from geosian.core.client import GeosianClient
from geosian.core.errors import ApiError, AuthError, ForbiddenError, NotFoundError
from geosian.core.http import Response, Transport


class TransporteFalso(Transport):
    """Devuelve respuestas preparadas y apunta lo que le piden."""

    def __init__(self, respuestas=None):
        self.respuestas = respuestas or {}
        self.llamadas = []

    def request(self, method, url, headers=None, body=None, timeout=30):
        self.llamadas.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": json.loads(body) if body else None,
                "timeout": timeout,
            }
        )
        for patron, respuesta in self.respuestas.items():
            if patron in url:
                return respuesta
        return Response(200, b"{}")


def respuesta(datos, status=200):
    return Response(status, json.dumps(datos).encode("utf-8"))


def test_login_guarda_las_dos_credenciales():
    transporte = TransporteFalso(
        {
            "/users/login/": respuesta(
                {
                    "api_token": "tok123",
                    "jwt_token": "jwt456",
                    "user": {"email": "a@b.c"},
                },
                202,
            )
        }
    )
    cliente = GeosianClient("https://api.ejemplo.com", transporte)
    cliente.login("a@b.c", "secreto")

    assert cliente.token == "tok123"
    assert cliente.jwt == "jwt456"
    assert cliente.authenticated


def test_login_con_doble_factor_no_da_token_todavia():
    transporte = TransporteFalso(
        {"/users/login/": respuesta({"mfa_required": True, "mfa_token": "mfa"}, 202)}
    )
    cliente = GeosianClient("https://api.ejemplo.com", transporte)
    resultado = cliente.login("a@b.c", "secreto")

    assert resultado["mfa_required"]
    assert not cliente.authenticated


def test_segundo_factor_va_a_la_ruta_con_barra():
    transporte = TransporteFalso(
        {
            "/users/login/verify-2fa/": respuesta(
                {"api_token": "tok123", "jwt_token": "jwt456"}, 202
            )
        }
    )
    cliente = GeosianClient("https://api.ejemplo.com", transporte)
    cliente.verify_2fa("mfa", "123456")

    # Sin la barra, Django responde con una redirección y QGIS no la sigue.
    assert transporte.llamadas[0]["url"].endswith("/users/login/verify-2fa/")
    assert transporte.llamadas[0]["body"]["otp_code"] == "123456"
    assert cliente.token == "tok123"


def test_cabecera_de_autorizacion():
    transporte = TransporteFalso({"/maps/": respuesta([])})
    cliente = GeosianClient("https://api.ejemplo.com", transporte, token="tok")
    cliente.maps()

    assert transporte.llamadas[0]["headers"]["Authorization"] == "Token tok"


def test_traduccion_de_errores():
    casos = [
        (401, AuthError),
        (403, ForbiddenError),
        (404, NotFoundError),
        (500, ApiError),
    ]
    for status, esperado in casos:
        transporte = TransporteFalso(
            {"/maps/": respuesta({"detail": "no"}, status)}
        )
        cliente = GeosianClient("https://api.ejemplo.com", transporte, token="t")
        with pytest.raises(esperado):
            cliente.maps()


def test_listas_paginadas_y_en_bruto():
    transporte = TransporteFalso({"/maps/": respuesta({"results": [{"id": 1}]})})
    cliente = GeosianClient("https://x", transporte, token="t")
    assert cliente.maps() == [{"id": 1}]

    transporte = TransporteFalso({"/maps/": respuesta([{"id": 2}])})
    cliente = GeosianClient("https://x", transporte, token="t")
    assert cliente.maps() == [{"id": 2}]


def test_geodata_arma_bien_la_consulta():
    transporte = TransporteFalso({"/geodata/": respuesta({"features": []})})
    cliente = GeosianClient("https://x", transporte, token="t")
    cliente.geodata(11, data_type="points", ids=[1, 2, 3], no_geometry=True)

    url = transporte.llamadas[0]["url"]
    assert "layer_id=11" in url
    assert "data_type=points" in url
    assert "ids=1%2C2%2C3" in url
    assert "no_geometry=true" in url
    assert "response_format=geojson" in url


def test_layer_metadata_sale_del_listado_del_mapa():
    transporte = TransporteFalso(
        {
            "/maps/4/layers/": respuesta(
                [
                    {"id": 10, "tile_metadata": {"feature_count": 7}},
                    {"id": 11, "tile_metadata": {"feature_count": 42}},
                ]
            )
        }
    )
    cliente = GeosianClient("https://x", transporte, token="t")
    assert cliente.layer_metadata(11, 4)["feature_count"] == 42
    # El detalle /layers/<id>/ no trae los metadatos aunque se le pidan.
    assert "/maps/4/layers/" in transporte.llamadas[0]["url"]
    assert "include_tile_metadata=true" in transporte.llamadas[0]["url"]


def test_listado_de_capas_se_reutiliza_al_abrir_varias():
    transporte = TransporteFalso(
        {"/maps/4/layers/": respuesta([{"id": 10}, {"id": 11}])}
    )
    cliente = GeosianClient("https://x", transporte, token="t")
    cliente.layer_metadata(10, 4)
    cliente.layer_metadata(11, 4)
    assert len(transporte.llamadas) == 1

    cliente.forget_layers()
    cliente.layers(4)
    assert len(transporte.llamadas) == 2


def test_los_lad_se_piden_juntos_y_se_reutilizan():
    transporte = TransporteFalso(
        {"/layer-attributes/": respuesta([{"id": 1, "schema": {"title": "X"}}])}
    )
    cliente = GeosianClient("https://x", transporte, token="t")
    cliente.prefetch_layer_attributes([10, 11])
    assert len(transporte.llamadas) == 2

    assert cliente.layer_attributes(10)[0]["schema"]["title"] == "X"
    cliente.prefetch_layer_attributes([10, 11])
    assert len(transporte.llamadas) == 2  # ya estaban


def test_url_del_websocket():
    cliente = GeosianClient("https://api.ejemplo.com", TransporteFalso())
    assert cliente.websocket_url() == "wss://api.ejemplo.com/ws/layer-data/"

    cliente = GeosianClient("http://localhost:8000", TransporteFalso())
    assert cliente.websocket_url() == "ws://localhost:8000/ws/layer-data/"


def test_el_token_no_viaja_en_la_url_del_websocket():
    cliente = GeosianClient("https://x", TransporteFalso())
    cliente.jwt = "secreto"
    assert "secreto" not in cliente.websocket_url()
    assert "token.secreto" in cliente.websocket_subprotocols()


def test_la_definicion_de_una_capa_espera_menos_que_los_datos():
    """Abrir una capa pide su definición en el hilo de la ventana: con el servidor
    mudo, QGIS se quedaba congelado los 30 s enteros. Los datos van en los hilos de
    pintado y conservan los 30 s."""
    t = TransporteFalso({"/layer-attributes/": respuesta([]), "/layers/": respuesta([])})
    cliente = GeosianClient("https://geo.example.com", transport=t, token="x")
    cliente.layer_attributes(11)
    cliente.layers(4)
    cliente.layer_view(3)
    cliente.geodata_paginated(11)
    tiempos = {c["url"].split("?")[0].rsplit("/api/v1/", 1)[1]: c["timeout"] for c in t.llamadas}
    assert tiempos["layer-attributes/"] == 15
    assert tiempos["maps/4/layers/"] == 15
    assert tiempos["layer-views/3/"] == 15
    assert tiempos["geodata/paginated/"] == 30
