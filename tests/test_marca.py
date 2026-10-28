"""La marca del complemento, con su versión, llega al servidor en el User-Agent.

El servidor anota el User-Agent en las sesiones y en los registros de actividad:
es lo que dice que una petición vino del complemento y de qué versión.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from geosian.core.http import MARCA, VERSION, UrllibTransport


class _Eco(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.agentes.append(self.headers.get("User-Agent"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def eco():
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Eco)
    servidor.agentes = []
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield servidor
    servidor.shutdown()


def test_la_marca_lleva_la_version_del_metadata():
    assert VERSION and VERSION != "desconocida"
    assert MARCA == f"GreenCityControl-QGIS/{VERSION}"


def test_urllib_manda_la_marca(eco):
    UrllibTransport().request("GET", f"http://127.0.0.1:{eco.server_port}/a")
    assert eco.agentes == [MARCA]


def test_qgis_manda_su_user_agent_y_la_marca_detras(eco, app):
    from geosian.core.http import QgisTransport, quitar_marca, registrar_marca

    url = f"http://127.0.0.1:{eco.server_port}"
    registrar_marca()
    try:
        QgisTransport().request("GET", f"{url}/una")
        QgisTransport().get_many([f"{url}/varias"])
    finally:
        quitar_marca()
    QgisTransport().request("GET", f"{url}/sin-marca")

    con_marca, en_paralelo, sin_marca = eco.agentes
    assert con_marca.startswith("Mozilla/5.0 QGIS/")
    assert con_marca.endswith(f" {MARCA}")
    assert en_paralelo == con_marca
    # Quitado el preprocesador, QGIS vuelve a pisar el User-Agent con el suyo.
    assert MARCA not in sin_marca
