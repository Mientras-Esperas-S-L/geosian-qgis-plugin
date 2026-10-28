"""Diálogo de conexión.

Pide servidor y credenciales, resuelve el segundo factor si el servidor lo
exige, pide una contraseña nueva si la que hay es provisional o ha caducado, y
guarda la conexión.

Avisa de algo que el usuario tiene que saber antes de pulsar: entrar desde aquí
cierra la sesión que tenga abierta en el navegador, porque la plataforma no
permite dos sesiones a la vez salvo a los administradores.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..core import connections, servidor
from ..core.client import GeosianClient
from ..core.errors import ApiError, AuthError, GeosianError

AVISO_SESION = (
    "Al entrar desde QGIS se cerrará la sesión que tengas abierta en el "
    "navegador. Es el funcionamiento normal de la plataforma: una sesión por "
    "usuario."
)


def url_insegura(url):
    """Por qué no vale ``url`` para conectar, o None.

    Por ``http://`` la contraseña, el código del doble factor y después el token viajan sin
    cifrar. Solo se admite contra el propio equipo (desarrollo).
    """
    from urllib.parse import urlsplit

    partes = urlsplit(url)
    if partes.scheme == "https" and partes.hostname:
        return None
    if partes.scheme == "http" and partes.hostname in ("localhost", "127.0.0.1", "::1"):
        return None
    if partes.scheme == "http":
        return "La dirección tiene que empezar por https://: por http:// la contraseña y la sesión viajarían sin cifrar."
    return "La dirección no es válida: tiene que ser como https://app.greencitycontrol.com"


class ConnectionDialog(QDialog):
    """Alta o edición de una conexión."""

    def __init__(self, parent=None, nombre=None):
        super().__init__(parent)
        self.setWindowTitle(f"Conectar con {servidor.titulo()}")
        self.setMinimumWidth(420)
        self._nombre_original = nombre
        self.connection_name = None

        formulario = QFormLayout()

        self.txt_nombre = QLineEdit()
        self.txt_nombre.setPlaceholderText("Producción")
        formulario.addRow("Nombre", self.txt_nombre)

        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("https://api.greencitycontrol.com")
        # Paquete con servidor fijado (`make package SERVIDOR=...`): se ve a cuál se conecta,
        # pero no se puede cambiar.
        if servidor.fijo():
            self.txt_url.setText(servidor.fijo())
            self.txt_url.setReadOnly(True)
        formulario.addRow("Servidor", self.txt_url)

        self.txt_email = QLineEdit()
        self.txt_email.setPlaceholderText("usuario@ejemplo.com")
        formulario.addRow("Correo", self.txt_email)

        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        formulario.addRow("Contraseña", self.txt_password)

        self.chk_guardar = QCheckBox("Recordar esta conexión")
        self.chk_guardar.setChecked(True)
        formulario.addRow("", self.chk_guardar)

        aviso = QLabel(AVISO_SESION)
        aviso.setWordWrap(True)
        aviso.setTextFormat(Qt.TextFormat.PlainText)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, Qt.Orientation.Horizontal, self
        )
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Conectar")
        botones.accepted.connect(self._conectar)
        botones.rejected.connect(self.reject)
        self._botones = botones

        disposicion = QVBoxLayout(self)
        if servidor.entorno():
            marca = QLabel("Versión de PRUEBAS: se conecta a devel, no a producción. Lo que hagas aquí no llega a los datos reales.")
            marca.setWordWrap(True)
            marca.setStyleSheet("font-weight: bold; color: #b45309;")
            disposicion.addWidget(marca)
        disposicion.addLayout(formulario)
        disposicion.addWidget(aviso)
        disposicion.addWidget(self.lbl_estado)
        disposicion.addWidget(botones)

        if nombre:
            self._cargar(nombre)

    def _cargar(self, nombre):
        conexion = connections.get_connection(nombre)
        if not conexion:
            return
        self.txt_nombre.setText(conexion["name"])
        self.txt_url.setText(servidor.fijo() or conexion["url"])
        self.txt_email.setText(conexion.get("email", ""))

    def _conectar(self):
        nombre = self.txt_nombre.text().strip()
        url = servidor.fijo() or self.txt_url.text().strip()
        email = self.txt_email.text().strip()
        password = self.txt_password.text()

        if not (nombre and url and email and password):
            self.lbl_estado.setText("Faltan datos por rellenar.")
            return
        motivo = url_insegura(url)
        if motivo:
            self.lbl_estado.setText(motivo)
            return

        self._botones.setEnabled(False)
        self.lbl_estado.setText("Conectando...")
        try:
            cliente = GeosianClient(url)
            resultado = cliente.login(email, password)

            doble_factor = resultado.get("mfa_required") or resultado.get("mfa_setup_required")
            if doble_factor and not self._resolver_2fa(cliente, resultado):
                return

            if not cliente.authenticated:
                self.lbl_estado.setText("El servidor no devolvió ninguna credencial.")
                return

            # Contraseña provisional (alta nueva, reseteo) o caducada: igual que la web, no
            # se entra sin cambiarla. Sin esto, quien solo usa QGIS no la cambiaría nunca.
            if cliente.requiere_cambio_contrasena and not self._cambiar_contrasena(cliente, password):
                return

            if self.chk_guardar.isChecked():
                connections.save_connection(
                    nombre, url, email, cliente.token, cliente.jwt
                )
            else:
                connections.save_connection(nombre, url, email)
                connections.set_session(nombre, cliente.token, cliente.jwt)

            self.connection_name = nombre
            self.accept()

        except AuthError:
            self.lbl_estado.setText("Correo o contraseña incorrectos.")
        except GeosianError as exc:
            self.lbl_estado.setText(str(exc))
        finally:
            self._botones.setEnabled(True)

    def _cambiar_contrasena(self, cliente, actual):
        """Pide la contraseña nueva hasta que el servidor la acepte o se cancele."""
        dialogo = CambioContrasenaDialog(cliente, actual, self)
        if dialogo.exec():
            return True
        self.lbl_estado.setText(
            "Para entrar hay que cambiar la contraseña provisional. Vuelve a pulsar Conectar cuando quieras hacerlo."
        )
        return False

    def _resolver_2fa(self, cliente, resultado):
        """Pide el código del segundo factor y termina el login."""
        if resultado.get("mfa_setup_required"):
            QMessageBox.warning(
                self,
                "Falta configurar el segundo factor",
                "Esta cuenta todavía no tiene configurado el doble factor. "
                "Hay que configurarlo desde la aplicación web y volver a "
                "intentarlo aquí.",
            )
            return False

        codigo, aceptado = QInputDialog.getText(
            self,
            "Verificación en dos pasos",
            "Código de tu aplicación de autenticación:",
        )
        if not aceptado or not codigo.strip():
            self.lbl_estado.setText("Verificación cancelada.")
            return False

        try:
            cliente.verify_2fa(resultado.get("mfa_token"), codigo.strip())
        except AuthError:
            self.lbl_estado.setText("El código no es válido o ha caducado.")
            return False
        return True


class CambioContrasenaDialog(QDialog):
    """La contraseña nueva, cuando la que hay es provisional o ha caducado.

    La política (longitud, que no repita las anteriores…) la decide el servidor: aquí solo
    se comprueba que las dos casillas coinciden y que no es la misma, y si el servidor la
    rechaza se enseña su motivo y se puede volver a probar sin repetir el login.
    """

    def __init__(self, cliente, actual, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cambia tu contraseña")
        self.setMinimumWidth(400)
        self._cliente = cliente
        self._actual = actual

        explicacion = QLabel(
            "Tu contraseña es provisional o ha caducado. Elige una nueva para seguir: "
            "es la que usarás desde ahora, también en la web."
        )
        explicacion.setWordWrap(True)

        formulario = QFormLayout()
        self.txt_nueva = QLineEdit()
        self.txt_nueva.setEchoMode(QLineEdit.EchoMode.Password)
        formulario.addRow("Contraseña nueva", self.txt_nueva)
        self.txt_repetida = QLineEdit()
        self.txt_repetida.setEchoMode(QLineEdit.EchoMode.Password)
        formulario.addRow("Repítela", self.txt_repetida)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setTextFormat(Qt.TextFormat.PlainText)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, Qt.Orientation.Horizontal, self
        )
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Cambiar")
        botones.accepted.connect(self._cambiar)
        botones.rejected.connect(self.reject)
        self._botones = botones

        disposicion = QVBoxLayout(self)
        disposicion.addWidget(explicacion)
        disposicion.addLayout(formulario)
        disposicion.addWidget(self.lbl_estado)
        disposicion.addWidget(botones)

    def _cambiar(self):
        nueva = self.txt_nueva.text()
        if not nueva:
            self.lbl_estado.setText("Escribe la contraseña nueva.")
            return
        if nueva != self.txt_repetida.text():
            self.lbl_estado.setText("Las dos contraseñas no coinciden.")
            return
        if nueva == self._actual:
            self.lbl_estado.setText("La nueva tiene que ser distinta de la provisional.")
            return

        self._botones.setEnabled(False)
        self.lbl_estado.setText("Cambiando...")
        try:
            self._cliente.cambiar_contrasena(self._actual, nueva)
        except ApiError as exc:
            # El motivo del servidor: corta, repetida, demasiado parecida al correo…
            self.lbl_estado.setText(exc.args[0] if exc.args else str(exc))
            return
        except GeosianError as exc:
            self.lbl_estado.setText(str(exc))
            return
        finally:
            self._botones.setEnabled(True)
        self.accept()
