"""Canal de tiempo real de Geosian (``/ws/layer-data/``), sin QGIS delante.

El servidor avisa por aquí de lo que cambia en los mapas a los que uno se
suscribe (``layer_data_changed``, ``layer_schema_changed``…), que es lo que usa
la web para recargar solo lo tocado (``useLayerDataWebSocket.js``).

Es un cliente WebSocket mínimo en Python, sin dependencias: el QGIS de cada
usuario no siempre trae el módulo de WebSockets de Qt. Solo hace lo que el
protocolo de Geosian necesita: mensajes de texto JSON, sin fragmentar.

La credencial es el JWT del login, por subprotocolo (``token.<jwt>``) como la
web, para que no acabe en los registros de acceso. Si el servidor la rechaza
(cierre 4001) no se reintenta: se avisa con ``{"type": "auth_failed"}``.
"""

import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
from urllib.parse import urlparse

RECHAZO_CREDENCIAL = 4001
ESPERA_MAXIMA = 60  # segundos entre reintentos, como mucho


def ws_url(api_url):
    """``wss://<api>/ws/layer-data/`` a partir de la URL de la API."""
    base = (api_url or "").rstrip("/")
    if base.startswith("https:"):
        base = "wss:" + base[len("https:"):]
    elif base.startswith("http:"):
        base = "ws:" + base[len("http:"):]
    return base + "/ws/layer-data/"


def origin_of(api_url):
    """Cabecera ``Origin`` para el saludo: la de la propia API.

    Channels (``AllowedHostsOriginValidator``) rechaza con 403 a quien no manda
    ``Origin``, que es lo que hace un cliente que no es navegador. La de la API
    está entre los hosts permitidos; la credencial sigue siendo el JWT.
    """
    partes = urlparse(api_url or "")
    return f"{partes.scheme}://{partes.netloc}"


class LayerDataChannel:
    """Conexión al canal con reconexión, latido y suscripciones.

    Args:
        url: la del canal (:func:`ws_url`).
        jwt: el JWT de la sesión.
        on_message: se llama con cada mensaje (un ``dict``) desde el hilo del
            canal; quien lo use en la interfaz lo tiene que pasar a su hilo.
        heartbeat: segundos entre latidos; la web manda uno cada 25.
        origin: la cabecera ``Origin`` (:func:`origin_of`).
    """

    def __init__(self, url, jwt, on_message, heartbeat=25, timeout=10, origin=None):
        self._url = url
        self._origin = origin
        self._jwt = jwt
        self._on_message = on_message
        self._heartbeat = heartbeat
        self._timeout = timeout
        self._mapas = set()
        self._lock = threading.Lock()
        self._sock = None
        self._parar = threading.Event()
        self._hilo = None
        self._pendiente = b""

    def subscribe(self, map_id):
        with self._lock:
            nuevo = map_id not in self._mapas
            self._mapas.add(map_id)
        if nuevo and self._sock is not None:
            self._send({"type": "subscribe_map", "map_id": map_id})

    def start(self):
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="geosian-ws", daemon=True)
        self._hilo.start()

    def stop(self):
        self._parar.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def is_running(self):
        return self._hilo is not None and self._hilo.is_alive()

    # ------------------------------------------------------------------

    def _bucle(self):
        intento = 0
        while not self._parar.is_set():
            try:
                self._conectar()
                intento = 0
                with self._lock:
                    mapas = sorted(self._mapas)
                for map_id in mapas:
                    self._send({"type": "subscribe_map", "map_id": map_id})
                if self._escuchar() == RECHAZO_CREDENCIAL:
                    self._on_message({"type": "auth_failed"})
                    return
            except (OSError, ConnectionError, ValueError):
                pass
            finally:
                sock, self._sock = self._sock, None
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            intento += 1
            self._parar.wait(min(ESPERA_MAXIMA, 2 ** min(intento, 6)))

    def _conectar(self):
        partes = urlparse(self._url)
        seguro = partes.scheme == "wss"
        puerto = partes.port or (443 if seguro else 80)
        sock = socket.create_connection((partes.hostname, puerto), timeout=self._timeout)
        if seguro:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=partes.hostname)
        clave = base64.b64encode(os.urandom(16)).decode()
        ruta = partes.path or "/"
        if partes.query:
            ruta += "?" + partes.query
        anfitrion = partes.hostname + (f":{partes.port}" if partes.port else "")
        sock.sendall(
            (
                f"GET {ruta} HTTP/1.1\r\nHost: {anfitrion}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {clave}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                + (f"Origin: {self._origin}\r\n" if self._origin else "")
                + f"Sec-WebSocket-Protocol: geosian, token.{self._jwt}\r\n\r\n"
            ).encode()
        )
        respuesta = b""
        while b"\r\n\r\n" not in respuesta:
            trozo = sock.recv(1024)
            if not trozo:
                raise ConnectionError("el servidor cerró durante el saludo")
            respuesta += trozo
        cabecera, _, resto = respuesta.partition(b"\r\n\r\n")
        if b" 101 " not in cabecera.split(b"\r\n", 1)[0]:
            raise ConnectionError(cabecera.split(b"\r\n", 1)[0].decode(errors="replace"))
        sock.settimeout(1.0)  # para poder mirar si hay que parar o latir
        self._sock = sock
        self._pendiente = resto

    def _escuchar(self):
        """Lee mensajes hasta que se cierre. Devuelve el código de cierre."""
        ultimo_latido = time.monotonic()
        while not self._parar.is_set():
            if time.monotonic() - ultimo_latido >= self._heartbeat:
                self._send({"type": "heartbeat"})
                ultimo_latido = time.monotonic()
            try:
                opcode, datos = self._leer_marco()
            except TimeoutError:
                continue
            if opcode == 0x8:
                return struct.unpack("!H", datos[:2])[0] if len(datos) >= 2 else None
            if opcode == 0x9:  # ping del servidor
                self._enviar_marco(datos, opcode=0xA)
            elif opcode == 0x1:
                try:
                    mensaje = json.loads(datos.decode())
                except ValueError:
                    continue
                if isinstance(mensaje, dict):
                    self._on_message(mensaje)
        return None

    def _leer_marco(self):
        cabeza = self._exacto(2)
        opcode = cabeza[0] & 0x0F
        largo = cabeza[1] & 0x7F
        if largo == 126:
            largo = struct.unpack("!H", self._exacto(2))[0]
        elif largo == 127:
            largo = struct.unpack("!Q", self._exacto(8))[0]
        mascara = self._exacto(4) if cabeza[1] & 0x80 else None
        datos = self._exacto(largo)
        if mascara:
            datos = bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))
        return opcode, datos

    def _exacto(self, n):
        datos = self._pendiente[:n]
        self._pendiente = self._pendiente[n:]
        while len(datos) < n:
            sock = self._sock
            if sock is None:
                raise ConnectionError("canal cerrado")
            trozo = sock.recv(n - len(datos))
            if not trozo:
                raise ConnectionError("canal cerrado")
            datos += trozo
        return datos

    def _send(self, mensaje):
        try:
            self._enviar_marco(json.dumps(mensaje).encode())
        except (OSError, AttributeError):
            pass

    def _enviar_marco(self, datos, opcode=0x1):
        # Los marcos del cliente van enmascarados (RFC 6455, 5.3).
        mascara = os.urandom(4)
        largo = len(datos)
        if largo < 126:
            cabeza = struct.pack("!BB", 0x80 | opcode, 0x80 | largo)
        elif largo < 65536:
            cabeza = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, largo)
        else:
            cabeza = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, largo)
        cuerpo = bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))
        with self._lock:
            self._sock.sendall(cabeza + mascara + cuerpo)
