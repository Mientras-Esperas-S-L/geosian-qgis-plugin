"""La versión del complemento llega al servidor en todas sus peticiones.

El servidor la añade al User-Agent que anota en sesiones y registros: es lo que
dice que una petición vino del complemento y de qué versión.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from geosian.core.http import CABECERA_MARCA, VERSION, QgisTransport, UrllibTransport


class _Eco(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.recibidas.append(self.headers.get(CABECERA_MARCA))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def eco():
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Eco)
    servidor.recibidas = []
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield servidor
    servidor.shutdown()


def test_la_version_es_la_del_metadata():
    assert VERSION and VERSION != "desconocida"


def test_urllib_manda_la_version(eco):
    UrllibTransport().request("GET", f"http://127.0.0.1:{eco.server_port}/a")
    assert eco.recibidas == [VERSION]


def test_qgis_manda_la_version(eco, app):
    url = f"http://127.0.0.1:{eco.server_port}"
    QgisTransport().request("GET", f"{url}/una")
    QgisTransport().get_many([f"{url}/varias"])
    assert eco.recibidas == [VERSION, VERSION]
