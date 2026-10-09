"""Filtrar una capa por sus partes y por sus fechas, como el panel de filtros de la web.

Los filtros van en la URI de la capa (``provider/uri.py``), así que se guardan con
el proyecto y los resuelve el servidor: elementos con algún parte que cumpla cada
condición, y partes entre dos fechas (o solo el más reciente).
"""

from qgis.core import QgsDataProvider
from qgis.PyQt.QtCore import QDate, Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
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


def menu_de_filtros(menu, capa):
    """«Filtrar por partes y fechas…» en el menú de una capa de Geosian con partes."""
    if capa is None or not capa.isValid() or capa.providerType() != "geosian":
        return
    if not _tipos(capa) or capa.dataProvider().layer_uri.info_name:
        return
    accion = menu.addAction("Filtrar por partes y fechas…")
    accion.triggered.connect(lambda: FiltroPartesDialog(capa, menu.parentWidget()).exec())


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
        boton_añadir = QPushButton("Añadir")
        boton_quitar = QPushButton("Quitar")
        self.tipo.currentIndexChanged.connect(self._al_cambiar_tipo)
        self.campo.currentIndexChanged.connect(self._al_cambiar_campo)
        boton_añadir.clicked.connect(self.agregar)
        boton_quitar.clicked.connect(self._quitar)
        self._al_cambiar_tipo()

        condicion = QHBoxLayout()
        for widget in (self.tipo, self.campo, self.operador, self.valor, boton_añadir):
            condicion.addWidget(widget)

        self.usar_desde, self.desde = self._fecha(uri.date_from)
        self.usar_hasta, self.hasta = self._fecha(uri.date_to)
        self.ultimo = QCheckBox("Solo el parte más reciente de cada elemento")
        self.ultimo.setChecked(uri.most_recent)
        fechas = QFormLayout()
        fechas.addRow(self.usar_desde, self.desde)
        fechas.addRow(self.usar_hasta, self.hasta)
        self.usar_desde.setText("Partes desde")
        self.usar_hasta.setText("Partes hasta")

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
        caja.addWidget(boton_quitar, 0, Qt.AlignmentFlag.AlignRight)
        caja.addLayout(condicion)
        caja.addLayout(fechas)
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

    def _al_cambiar_campo(self):
        info = self._tipos.get(self.tipo.currentData()) or {}
        attr = next(
            (a for a in S.flatten_attributes(info) if a.get("name") == self.campo.currentData()),
            {},
        )
        valores = [str(v) for v in attr.get("allowed_values") or [] if not isinstance(v, dict)]
        self.valor.setCompleter(QCompleter(valores, self) if valores else None)

    def agregar(self):
        if not self.campo.currentData() or not self.valor.text().strip():
            return
        clave = f"{self.tipo.currentData()}__{self.campo.currentData()}"
        if self.operador.currentData():
            clave += f"__{self.operador.currentData()}"
        self._añadir_a_la_lista(clave, self.valor.text().strip())
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
