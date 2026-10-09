"""El canal de tiempo real (/ws/layer-data/), sin QGIS delante."""

import queue
import time

from geosian.core import realtime
from tests.fake_ws import FakeWebSocket


def _esperar(condicion, segundos=3):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def test_origen_a_partir_de_la_api():
    assert realtime.origin_of("https://api.devel.greencitycontrol.com/") == "https://api.devel.greencitycontrol.com"
    assert realtime.origin_of("http://localhost:8010") == "http://localhost:8010"


def test_url_del_canal_a_partir_de_la_api():
    assert realtime.ws_url("https://api.devel.greencitycontrol.com") == (
        "wss://api.devel.greencitycontrol.com/ws/layer-data/"
    )
    assert realtime.ws_url("http://localhost:8010/") == "ws://localhost:8010/ws/layer-data/"


def test_se_suscribe_a_los_mapas_y_entrega_los_cambios():
    servidor = FakeWebSocket()
    llegados = queue.Queue()
    canal = realtime.LayerDataChannel(
        servidor.url, "jwt-de-prueba", llegados.put, heartbeat=60,
        origin="https://api.ejemplo.org",
    )
    try:
        canal.subscribe(4)
        canal.start()
        assert servidor.conectado.wait(3)
        # El token va por subprotocolo, como en la web, y no en la URL.
        assert servidor.cabeceras["sec-websocket-protocol"] == "geosian, token.jwt-de-prueba"
        # Sin Origin, AllowedHostsOriginValidator de Channels rechaza con 403.
        assert servidor.cabeceras["origin"] == "https://api.ejemplo.org"
        assert _esperar(lambda: {"type": "subscribe_map", "map_id": 4} in servidor.recibidos)

        servidor.enviar({"type": "layer_data_changed", "map_id": 4, "layer_id": 11,
                         "change_type": "update", "feature_id": 1001})
        mensajes = []
        assert _esperar(lambda: mensajes.extend(_vaciar(llegados)) or any(
            m.get("type") == "layer_data_changed" for m in mensajes))
        cambio = next(m for m in mensajes if m.get("type") == "layer_data_changed")
        assert cambio["layer_id"] == 11 and cambio["feature_id"] == 1001

        # Suscribirse con el canal ya abierto también se manda.
        canal.subscribe(7)
        assert _esperar(lambda: {"type": "subscribe_map", "map_id": 7} in servidor.recibidos)
    finally:
        canal.stop()
        servidor.cerrar()


def test_credencial_rechazada_no_reintenta():
    # El servidor real acepta y cierra con 4001 si el JWT no vale.
    servidor = FakeWebSocket(cerrar_con=4001)
    llegados = queue.Queue()
    canal = realtime.LayerDataChannel(servidor.url, "caducado", llegados.put, heartbeat=60)
    try:
        canal.start()
        assert _esperar(lambda: not canal.is_running())
        assert {"type": "auth_failed"} in _vaciar(llegados)
    finally:
        canal.stop()
        servidor.cerrar()


def _vaciar(cola):
    salida = []
    while not cola.empty():
        salida.append(cola.get_nowait())
    return salida
