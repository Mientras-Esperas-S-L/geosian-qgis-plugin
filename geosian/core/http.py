"""Transporte HTTP.

Dos implementaciones tras la misma interfaz:

- ``QgisTransport`` usa la pila de red de QGIS, que respeta el proxy, los
  certificados y el gestor de autenticación que el usuario tenga configurados.
  Es la que se usa dentro de QGIS.
- ``UrllibTransport`` usa la biblioteca estándar. Sirve para las pruebas y para
  usar el cliente fuera de QGIS (scripts, integración continua).

El cliente de la API no sabe cuál tiene delante, así que se puede probar sin
levantar QGIS.
"""

import json
import urllib.error
import urllib.request

from .errors import NetworkError

DEFAULT_TIMEOUT = 30


class Response:
    """Respuesta cruda, común a los dos transportes."""

    def __init__(self, status, body, headers=None):
        self.status = status
        self.body = body or b""
        self.headers = headers or {}

    def json(self):
        """Cuerpo interpretado como JSON, o ``None`` si viene vacío."""
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self):
        return self.body.decode("utf-8", errors="replace")


class Transport:
    """Interfaz de transporte."""

    def request(self, method, url, headers=None, body=None, timeout=DEFAULT_TIMEOUT):
        raise NotImplementedError

    def get_many(self, urls, headers=None, timeout=DEFAULT_TIMEOUT):
        """Varios GET. Devuelve, por cada URL, su ``Response`` o la excepción.

        Por omisión van de uno en uno; el transporte de QGIS los lanza a la vez.
        """
        salida = []
        for url in urls:
            try:
                salida.append(self.request("GET", url, headers, timeout=timeout))
            except NetworkError as exc:
                salida.append(exc)
        return salida


class UrllibTransport(Transport):
    """Transporte de la biblioteca estándar."""

    def request(self, method, url, headers=None, body=None, timeout=DEFAULT_TIMEOUT):
        req = urllib.request.Request(url, data=body, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Response(resp.status, resp.read(), dict(resp.headers))
        except urllib.error.HTTPError as exc:
            # Un código de error no es un fallo de transporte: el cliente
            # necesita el cuerpo para sacar el mensaje que devuelve la API.
            return Response(exc.code, exc.read(), dict(exc.headers or {}))
        except urllib.error.URLError as exc:
            raise NetworkError(f"No se pudo conectar con {url}: {exc.reason}") from exc
        except OSError as exc:
            raise NetworkError(f"No se pudo conectar con {url}: {exc}") from exc


class QgisTransport(Transport):
    """Transporte sobre la pila de red de QGIS.

    ``QgsBlockingNetworkRequest`` bloquea el hilo desde el que se llama, que es
    justo lo que hace falta: el proveedor de datos se invoca desde los hilos de
    render de QGIS y ahí no se puede hacer nada asíncrono.
    """

    def request(self, method, url, headers=None, body=None, timeout=DEFAULT_TIMEOUT):
        from qgis.core import QgsBlockingNetworkRequest
        from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QUrl
        from qgis.PyQt.QtNetwork import QNetworkRequest

        request = QNetworkRequest(QUrl(url))
        for key, value in (headers or {}).items():
            request.setRawHeader(key.encode("utf-8"), str(value).encode("utf-8"))

        # Siempre a la red, nunca de la caché de QGIS. Sin esto, tras un aviso
        # del WebSocket la recarga devuelve la respuesta vieja que Qt tenía
        # guardada y el técnico sigue viendo el dato anterior. Comprobado: la
        # segunda petición no llegaba al servidor.
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork,
        )
        request.setAttribute(
            QNetworkRequest.Attribute.CacheSaveControlAttribute, False
        )

        # El tiempo de espera pedido, no el general de QGIS (60 s por omisión):
        # estas peticiones bloquean la interfaz mientras duran.
        request.setTransferTimeout(int(timeout * 1000))

        blocking = QgsBlockingNetworkRequest()

        # El cuerpo va en un QBuffer y no en un QByteArray: QGIS 4 espera un
        # QIODevice. Hay que conservar la referencia hasta que termine la
        # petición o Qt se queda leyendo un objeto ya destruido.
        buffer = None
        if body:
            buffer = QBuffer()
            buffer.setData(QByteArray(body))
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)

        # forceRefresh=True en todo lo que lo admita. Por omisión
        # QgsBlockingNetworkRequest pide con PreferCache y pisa el atributo de
        # caché que se le ponga a la petición, así que sin esto la segunda
        # lectura de una capa devuelve lo que Qt tenía guardado. Comprobado:
        # la petición salía del cliente y no llegaba al servidor.
        method = method.upper()
        if method == "GET":
            code = blocking.get(request, True)
        elif method == "POST":
            code = blocking.post(request, buffer, True)
        elif method == "PUT":
            code = blocking.put(request, buffer)
        elif method == "DELETE":
            code = blocking.deleteResource(request)
        else:
            raise NetworkError(f"Método no soportado: {method}")

        reply = blocking.reply()
        # Enum anidado: es la forma que exige Qt6 y que Qt5 también acepta.
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)

        # Sin código de estado no hubo respuesta HTTP: es un fallo de red y no
        # una respuesta de error de la API.
        if status is None:
            if code != QgsBlockingNetworkRequest.NoError:
                raise NetworkError(
                    network_reason(reply.error(), blocking.errorMessage(), timeout)
                    or f"No se pudo conectar con {url}"
                )
            raise NetworkError(f"Respuesta vacía de {url}")

        raw = {
            bytes(name).decode("latin-1"): bytes(reply.rawHeader(name)).decode("latin-1")
            for name in reply.rawHeaderList()
        }
        return Response(int(status), bytes(reply.content()), raw)

    def get_many(self, urls, headers=None, timeout=DEFAULT_TIMEOUT):
        return _get_many_qgis(urls, headers, timeout)


def _get_many_qgis(urls, headers, timeout):
    """GET en paralelo sobre el gestor de red de QGIS, esperando a todos."""
    from functools import partial

    from qgis.core import QgsNetworkAccessManager
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest

    gestor = QgsNetworkAccessManager.instance()
    salida = [None] * len(urls)
    pendientes = set()
    bucle = QEventLoop()

    def terminado(i, respuesta):
        estado = respuesta.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if estado is None:
            salida[i] = NetworkError(
                respuesta.errorString() or f"No se pudo conectar con {urls[i]}"
            )
        else:
            salida[i] = Response(int(estado), bytes(respuesta.readAll()))
        respuesta.deleteLater()
        pendientes.discard(i)
        if not pendientes:
            bucle.quit()

    respuestas = []
    for i, url in enumerate(urls):
        peticion = QNetworkRequest(QUrl(url))
        for clave, valor in (headers or {}).items():
            peticion.setRawHeader(clave.encode("utf-8"), str(valor).encode("utf-8"))
        # Igual que en ``request``: siempre a la red, nunca a la caché de Qt.
        peticion.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork,
        )
        peticion.setAttribute(QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
        respuesta = gestor.get(peticion)
        pendientes.add(i)
        respuesta.finished.connect(partial(terminado, i, respuesta))
        respuestas.append(respuesta)  # que no las recoja el recolector

    if pendientes:
        QTimer.singleShot(int(timeout * 1000), bucle.quit)
        bucle.exec()

    for i in list(pendientes):
        respuestas[i].abort()
        salida[i] = NetworkError(f"Tiempo agotado esperando a {urls[i]}")
    return salida


def default_transport():
    """El transporte de QGIS si estamos dentro de QGIS, si no el estándar."""
    try:
        from qgis.core import QgsBlockingNetworkRequest  # noqa: F401

        return QgisTransport()
    except ImportError:
        return UrllibTransport()


def network_reason(codigo, mensaje, timeout):
    """El motivo de un fallo de red en castellano; Qt lo da en inglés.

    Args:
        codigo: el ``QNetworkReply.NetworkError`` de la respuesta.
        mensaje: el texto de Qt, que se queda si el código no es de los conocidos.
    """
    from qgis.PyQt.QtNetwork import QNetworkReply

    e = QNetworkReply.NetworkError
    motivos = {
        e.TimeoutError: f"GCC no ha respondido en {timeout:g} s",
        # Así termina QGIS una petición que pasa del tiempo de espera.
        e.OperationCanceledError: f"GCC no ha respondido en {timeout:g} s",
        e.HostNotFoundError: "no se encuentra el servidor (¿hay conexión a Internet?)",
        e.ConnectionRefusedError: "el servidor no acepta conexiones",
        e.RemoteHostClosedError: "la conexión se ha cortado",
        e.ProxyConnectionClosedError: "la conexión se ha cortado en el proxy",
        e.ProxyConnectionRefusedError: "el proxy no acepta conexiones",
        e.ProxyNotFoundError: "no se encuentra el proxy",
        e.NetworkSessionFailedError: "no hay conexión de red",
        e.TemporaryNetworkFailureError: "no hay conexión de red",
    }
    return motivos.get(codigo, mensaje)
