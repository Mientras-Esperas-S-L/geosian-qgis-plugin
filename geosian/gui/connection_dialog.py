"""Diálogo de conexión.

Pide servidor y credenciales, resuelve el segundo factor si el servidor lo
exige y guarda la conexión.

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

from ..core import connections
from ..core.client import GeosianClient
from ..core.errors import AuthError, GeosianError

AVISO_SESION = (
    "Al entrar desde QGIS se cerrará la sesión que tengas abierta en el "
    "navegador. Es el funcionamiento normal de la plataforma: una sesión por "
    "usuario."
)


class ConnectionDialog(QDialog):
    """Alta o edición de una conexión."""

    def __init__(self, parent=None, nombre=None):
        super().__init__(parent)
        self.setWindowTitle("Conectar con Geosian")
        self.setMinimumWidth(420)
        self._nombre_original = nombre
        self.connection_name = None

        formulario = QFormLayout()

        self.txt_nombre = QLineEdit()
        self.txt_nombre.setPlaceholderText("Producción")
        formulario.addRow("Nombre", self.txt_nombre)

        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("https://api.greencitycontrol.com")
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
        self.txt_url.setText(conexion["url"])
        self.txt_email.setText(conexion.get("email", ""))

    def _conectar(self):
        nombre = self.txt_nombre.text().strip()
        url = self.txt_url.text().strip()
        email = self.txt_email.text().strip()
        password = self.txt_password.text()

        if not (nombre and url and email and password):
            self.lbl_estado.setText("Faltan datos por rellenar.")
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
