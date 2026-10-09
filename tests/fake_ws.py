"""Servidor WebSocket mínimo para las pruebas, como el de /ws/layer-data/.

Acepta el subprotocolo «geosian», guarda lo que recibe y deja mandar mensajes
al cliente. Solo marcos de texto sin fragmentar: lo que usa el servidor real.
"""

import base64
import hashlib
import json
import socket
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeWebSocket:
    def __init__(self, cerrar_con=None):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.recibidos = []
        self.cabeceras = {}
        self.conectado = threading.Event()
        self._conexion = None
        self._cerrar_con = cerrar_con
        threading.Thread(target=self._aceptar, daemon=True).start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self._server.getsockname()[1]}/ws/layer-data/"

    def _aceptar(self):
        try:
            conexion, _ = self._server.accept()
        except OSError:
            return
        self._conexion = conexion
        peticion = b""
        while b"\r\n\r\n" not in peticion:
            peticion += conexion.recv(1024)
        lineas = peticion.decode().split("\r\n")
        for linea in lineas[1:]:
            if ":" in linea:
                clave, valor = linea.split(":", 1)
                self.cabeceras[clave.strip().lower()] = valor.strip()
        acepta = base64.b64encode(
            hashlib.sha1((self.cabeceras["sec-websocket-key"] + GUID).encode()).digest()
        ).decode()
        conexion.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Accept: {acepta}\r\n"
                "Sec-WebSocket-Protocol: geosian\r\n\r\n"
            ).encode()
        )
        self.conectado.set()
        if self._cerrar_con is not None:
            self._marco(struct.pack("!H", self._cerrar_con), opcode=0x8)
            return
        while True:
            try:
                texto = self._leer()
            except (OSError, ConnectionError):
                return
            if texto is None:
                return
            mensaje = json.loads(texto)
            self.recibidos.append(mensaje)
            if mensaje.get("type") == "subscribe_map":
                self.enviar({"type": "subscribed", "map_id": mensaje["map_id"]})

    def _leer(self):
        cabeza = self._exacto(2)
        opcode = cabeza[0] & 0x0F
        largo = cabeza[1] & 0x7F
        if largo == 126:
            largo = struct.unpack("!H", self._exacto(2))[0]
        elif largo == 127:
            largo = struct.unpack("!Q", self._exacto(8))[0]
        mascara = self._exacto(4) if cabeza[1] & 0x80 else b"\0\0\0\0"
        datos = bytes(b ^ mascara[i % 4] for i, b in enumerate(self._exacto(largo)))
        if opcode == 0x8:
            return None
        return datos.decode()

    def _exacto(self, n):
        datos = b""
        while len(datos) < n:
            trozo = self._conexion.recv(n - len(datos))
            if not trozo:
                raise ConnectionError("cerrado")
            datos += trozo
        return datos

    def _marco(self, datos, opcode=0x1):
        largo = len(datos)
        if largo < 126:
            cabeza = struct.pack("!BB", 0x80 | opcode, largo)
        elif largo < 65536:
            cabeza = struct.pack("!BBH", 0x80 | opcode, 126, largo)
        else:
            cabeza = struct.pack("!BBQ", 0x80 | opcode, 127, largo)
        self._conexion.sendall(cabeza + datos)

    def enviar(self, mensaje):
        self._marco(json.dumps(mensaje).encode())

    def cerrar(self):
        try:
            if self._conexion is not None:
                self._conexion.close()
        finally:
            self._server.close()
