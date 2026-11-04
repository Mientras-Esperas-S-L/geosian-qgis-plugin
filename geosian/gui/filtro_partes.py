"""Filtrar una capa por sus partes y por sus fechas, como el panel de filtros de la web.

Los filtros van en la URI de la capa (``provider/uri.py``), así que se guardan con
el proyecto y los resuelve el servidor: elementos con algún parte que cumpla cada
condición, y partes entre dos fechas (o solo el más reciente).
"""

from qgis.core import QgsDataProvider, QgsProject
from qgis.PyQt.QtCore import QDate, Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..core import schema as S
from ..provider.uri import parse_uri

OPERADORES = [("=", ""), ("≥", "gte"), (">", "gt"), ("≤", "lte"), ("<", "lt")]
FORMATO = "yyyy-MM-dd"


def menu_de_filtros(menu, capa, padre=None):
    """«Filtrar por partes y fechas…» en el menú de una capa de Geosian con partes.

    El diálogo no se abre dentro de la acción del menú, sino justo después. QGIS
    borra el menú del panel de capas en cuanto se cierra, y un diálogo modal
    abierto dentro de su acción vuelve a un menú que ya no existe: en Windows,
    QGIS se cerraba de golpe al aplicar el filtro (04/11/2026).
    """
    if capa is None or not capa.isValid() or capa.providerType() != "geosian":
        return
    if not _tipos(capa) or capa.dataProvider().layer_uri.info_name:
        return
    accion = menu.addAction("Filtrar por partes y fechas…")
    capa_id = capa.id()
    accion.triggered.connect(
        lambda _=False: QTimer.singleShot(0, lambda: abrir_filtro(capa_id, padre))
    )


def abrir_filtro(capa_id, padre=None):
    """Abre el diálogo de la capa, si sigue en el proyecto, y lo suelta al cerrarlo."""
    capa = QgsProject.instance().mapLayer(capa_id)
    if capa is None or not capa.isValid():
        return
    dialogo = FiltroPartesDialog(capa, padre)
    try:
        dialogo.exec()
    finally:
        dialogo.deleteLater()


def _tipos(capa):
    esquema = getattr(capa.dataProvider(), "schema", None) or {}
    return [
        info
        for info in esquema.get("additional_information") or []
        if isinstance(info, dict) and info.get("name")
    ]


class FiltroPartesDialog(QDialog):
    def __init__(self, capa, parent=None):
        super().__init__(parent)
        self.capa = capa
        self._tipos = {info["name"]: info for info in _tipos(capa)}
        uri = capa.dataProvider().layer_uri
        self.setWindowTitle(f"Filtrar «{capa.name()}» por partes y fechas")

        self.lista = QListWidget()
        for clave, valor in uri.partes:
            self._añadir_a_la_lista(clave, valor)

        self.tipo = QComboBox()
        for nombre, info in self._tipos.items():
            self.tipo.addItem(info.get("title") or nombre, nombre)
        self.campo = QComboBox()
        self.operador = QComboBox()
        for texto, op in OPERADORES:
            self.operador.addItem(texto, op)
        self.valor = QLineEdit()
        self.valor.setPlaceholderText("Valor")
        # Los campos con lista de valores (una casilla por valor, un desplegable) se
        # eligen de la lista: escribir a mano daba condiciones que nunca casan.
        self.valor_lista = QComboBox()
        self._con_lista = False
        boton_añadir = QPushButton("Añadir")
        boton_quitar = QPushButton("Quitar")
        boton_quitar_todo = QPushButton("Quitar todos los filtros")
        self.tipo.currentIndexChanged.connect(self._al_cambiar_tipo)
        self.campo.currentIndexChanged.connect(self._al_cambiar_campo)
        boton_añadir.clicked.connect(self.agregar)
        boton_quitar.clicked.connect(self._quitar)
        boton_quitar_todo.clicked.connect(self.quitar_todo)
        self._al_cambiar_tipo()

        condicion = QHBoxLayout()
        for widget in (
            self.tipo, self.campo, self.operador, self.valor, self.valor_lista, boton_añadir
        ):
            condicion.addWidget(widget)
        quitar = QHBoxLayout()
        quitar.addStretch()
        quitar.addWidget(boton_quitar)
        quitar.addWidget(boton_quitar_todo)

        self.usar_desde, self.desde = self._fecha(uri.date_from)
        self.usar_hasta, self.hasta = self._fecha(uri.date_to)
        self.ultimo = QCheckBox("Solo el parte más reciente de cada elemento")
        self.ultimo.setChecked(uri.most_recent)
        fechas = QFormLayout()
        fechas.addRow(self.usar_desde, self.desde)
        fechas.addRow(self.usar_hasta, self.hasta)
        self.usar_desde.setText("Partes desde")
        self.usar_hasta.setText("Partes hasta")
        aviso_fechas = QLabel(
            "Las fechas también filtran solas: con una marcada, solo quedan los "
            "elementos con algún parte en ese periodo."
        )
        aviso_fechas.setWordWrap(True)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)

        caja = QVBoxLayout(self)
        caja.addWidget(QLabel(
            "Elementos con algún parte que cumpla cada condición. Un mismo campo "
            "repetido vale cualquiera de sus valores."
        ))
        caja.addWidget(self.lista)
        caja.addLayout(quitar)
        caja.addLayout(condicion)
        caja.addLayout(fechas)
        caja.addWidget(aviso_fechas)
        caja.addWidget(self.ultimo)
        caja.addWidget(botones)

    def _fecha(self, texto):
        usar = QCheckBox()
        fecha = QDateEdit()
        fecha.setCalendarPopup(True)
        fecha.setDisplayFormat("dd/MM/yyyy")
        valor = QDate.fromString(texto or "", FORMATO)
        fecha.setDate(valor if valor.isValid() else QDate.currentDate())
        usar.setChecked(bool(texto))
        fecha.setEnabled(bool(texto))
        usar.toggled.connect(fecha.setEnabled)
        return usar, fecha

    def _al_cambiar_tipo(self):
        self.campo.clear()
        info = self._tipos.get(self.tipo.currentData()) or {}
        for attr in S.flatten_attributes(info):
            if not S.is_attachment(attr):
                self.campo.addItem(S.field_title(attr), attr["name"])
        self._al_cambiar_campo()

    def _atributo(self):
        info = self._tipos.get(self.tipo.currentData()) or {}
        return next(
            (a for a in S.flatten_attributes(info) if a.get("name") == self.campo.currentData()),
            {},
        )

    def _al_cambiar_campo(self):
        """Operadores y valores según el tipo del campo.

        Mayor y menor solo en números y fechas: en un texto o una lista no casan
        con nada. Y un campo con valores permitidos se elige de su lista.
        """
        attr = self._atributo()
        comparable = attr.get("type") in S.NUMERIC_TYPES | S.DATE_TYPES
        self.operador.clear()
        for texto, op in OPERADORES if comparable else OPERADORES[:1]:
            self.operador.addItem(texto, op)
        self.operador.setEnabled(comparable)
        valores = [str(v) for v in S.allowed_values(attr) if not isinstance(v, dict)]
        self._con_lista = bool(valores)
        self.valor_lista.clear()
        self.valor_lista.addItems(valores)
        self.valor_lista.setVisible(self._con_lista)
        self.valor.setVisible(not self._con_lista)
        self.valor.setPlaceholderText(
            "aaaa-mm-dd" if attr.get("type") in S.DATE_TYPES else "Valor"
        )

    def _valor_elegido(self):
        if self._con_lista:
            return self.valor_lista.currentText().strip()
        return self.valor.text().strip()

    def agregar(self):
        valor = self._valor_elegido()
        if not self.campo.currentData() or not valor:
            return
        clave = f"{self.tipo.currentData()}__{self.campo.currentData()}"
        if self.operador.currentData():
            clave += f"__{self.operador.currentData()}"
        self._añadir_a_la_lista(clave, valor)
        self.valor.clear()

    def _añadir_a_la_lista(self, clave, valor):
        tipo, _, resto = clave.partition("__")
        campo, _, op = resto.partition("__")
        info = self._tipos.get(tipo) or {}
        titulo_campo = next(
            (S.field_title(a) for a in S.flatten_attributes(info) if a.get("name") == campo),
            campo,
        )
        signo = next((t for t, o in OPERADORES if o == op), "=")
        texto = f"{info.get('title') or tipo}: {titulo_campo} {signo} {valor}"
        elemento = QListWidgetItem(texto)
        elemento.setData(Qt.ItemDataRole.UserRole, (clave, valor))
        self.lista.addItem(elemento)

    def _quitar(self):
        for elemento in self.lista.selectedItems():
            self.lista.takeItem(self.lista.row(elemento))

    def quitar_todo(self):
        """Condiciones, fechas y «solo el más reciente»: la capa entera otra vez."""
        self.lista.clear()
        self.usar_desde.setChecked(False)
        self.usar_hasta.setChecked(False)
        self.ultimo.setChecked(False)

    def accept(self):
        self.aplicar()
        super().accept()

    def aplicar(self):
        """Pone los filtros en la URI de la capa; el estilo y la ficha se quedan."""
        uri = parse_uri(self.capa.source())
        uri.partes = [
            tuple(self.lista.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.lista.count())
        ]
        uri.date_from = self.desde.date().toString(FORMATO) if self.usar_desde.isChecked() else None
        uri.date_to = self.hasta.date().toString(FORMATO) if self.usar_hasta.isChecked() else None
        uri.most_recent = self.ultimo.isChecked()
        self.capa.setDataSource(
            str(uri), self.capa.name(), "geosian", QgsDataProvider.ProviderOptions()
        )
        self.capa.triggerRepaint()
