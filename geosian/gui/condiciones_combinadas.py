"""«Condiciones combinadas…»: el constructor de filtros de la web, en QGIS.

Edita el árbol de ``core/filtro_arbol.py`` (grupos «todas»/«alguna», condiciones por tipo
de campo y bloques de partes cuyas condiciones se cumplen en el mismo parte) y lo deja en
la URI de la capa (``filtro=``), así que se guarda con el proyecto y lo resuelve el
servidor. Un servidor que aún no lo entienda no ofrece el diálogo.

Los métodos conectados a señales llevan nombres ASCII: en PyQt6 un método con «ñ»
conectado a una señal tumba QGIS (memoria del proyecto, 09/10/2026).
"""

import copy

from qgis.core import QgsDataProvider, QgsProject
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import connections
from ..core import filtro_arbol as F
from ..core import schema as S
from ..provider.uri import parse_uri

ROL_NODO = Qt.ItemDataRole.UserRole


def menu_de_condiciones(menu, capa, padre=None):
    """«Condiciones combinadas…» en el menú de una capa de Geosian (no en las de partes)."""
    if capa is None or not capa.isValid() or capa.providerType() != "geosian":
        return
    if capa.dataProvider().layer_uri.info_name:
        return
    accion = menu.addAction("Condiciones combinadas…")
    capa_id = capa.id()
    # Fuera de la acción del menú: QGIS lo borra al cerrarlo (gui/filtro_partes.py).
    accion.triggered.connect(lambda _=False: QTimer.singleShot(0, lambda: abrir_condiciones(capa_id, padre)))


def abrir_condiciones(capa_id, padre=None):
    capa = QgsProject.instance().mapLayer(capa_id)
    if capa is None or not capa.isValid():
        return
    uri = capa.dataProvider().layer_uri
    cliente = connections.client_for(uri.connection)
    if cliente is None or not cliente.admite_filtro_en_arbol(uri.layer_id):
        QMessageBox.information(
            padre,
            "Condiciones combinadas",
            "Este servidor de GreenCityControl todavía no admite condiciones combinadas.",
        )
        return
    dialogo = CondicionesDialog(capa, padre)
    try:
        dialogo.exec()
    finally:
        dialogo.deleteLater()


def _campos(atributos):
    campos = []
    for attr in S.flatten_attributes({"attributes": atributos}) if isinstance(atributos, list) else []:
        if S.is_attachment(attr) or not attr.get("name"):
            continue
        valores = [str(v) for v in S.allowed_values(attr) if not isinstance(v, dict)]
        campos.append({"name": attr["name"], "title": S.field_title(attr), "tipo": F.tipo_de_campo(attr), "valores": valores})
    return campos


class CondicionesDialog(QDialog):
    def __init__(self, capa, parent=None):
        super().__init__(parent)
        self.capa = capa
        self.setWindowTitle(f"Condiciones combinadas de «{capa.name()}»")
        uri = capa.dataProvider().layer_uri
        esquema = getattr(capa.dataProvider(), "schema", None) or {}
        self.campos = [{"name": "object_id", "title": "ID", "tipo": "texto", "valores": []}]
        self.campos += _campos(esquema.get("attributes") or [])
        self.formularios = {
            info["name"]: {"title": info.get("title") or info["name"], "campos": _campos(info.get("attributes") or [])}
            for info in esquema.get("additional_information") or []
            if isinstance(info, dict) and info.get("name")
        }
        self.arbol = copy.deepcopy(uri.filtro) if uri.filtro else {"todas": True, "condiciones": []}
        self._cargando = False

        self.frase = QLabel()
        self.frase.setWordWrap(True)
        self.raiz = QComboBox()
        self.raiz.addItem("todas", True)
        self.raiz.addItem("alguna", False)
        self.raiz.setCurrentIndex(0 if self.arbol.get("todas", True) else 1)
        self.raiz.currentIndexChanged.connect(self.cambiar_raiz)
        cabecera = QHBoxLayout()
        cabecera.addWidget(QLabel("Que cumplan"))
        cabecera.addWidget(self.raiz)
        cabecera.addWidget(QLabel("de estas condiciones"))
        cabecera.addStretch()

        self.vista = QTreeWidget()
        self.vista.setHeaderHidden(True)
        self.vista.currentItemChanged.connect(self.elegir)

        botones_arbol = QHBoxLayout()
        for texto, ranura in (
            ("Condición", self.anadir_condicion),
            ("Grupo", self.anadir_grupo),
            ("Partes", self.anadir_partes),
            ("Quitar", self.quitar),
        ):
            boton = QPushButton(texto)
            boton.clicked.connect(ranura)
            botones_arbol.addWidget(boton)
        self.boton_partes = botones_arbol.itemAt(2).widget()
        self.boton_partes.setEnabled(bool(self.formularios))

        self.editor = QStackedWidget()
        self.editor.addWidget(QLabel("Elige una condición, un grupo o un bloque de partes para editarlo."))
        self.editor.addWidget(self._editor_condicion())
        self.editor.addWidget(self._editor_grupo())
        self.editor.addWidget(self._editor_partes())

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)

        caja = QVBoxLayout(self)
        caja.addWidget(self.frase)
        caja.addLayout(cabecera)
        caja.addWidget(self.vista)
        caja.addLayout(botones_arbol)
        caja.addWidget(self.editor)
        caja.addWidget(botones)
        self.resize(640, 560)
        self.repintar()

    # ------------------------------------------------------------------ editores

    def _editor_condicion(self):
        pagina = QWidget()
        forma = QFormLayout(pagina)
        self.campo = QComboBox()
        self.operador = QComboBox()
        self.valor_texto = QLineEdit()
        self.valor_lista = QListWidget()
        self.desde = QLineEdit()
        self.hasta = QLineEdit()
        self.desde.setPlaceholderText("desde")
        self.hasta.setPlaceholderText("hasta")
        rango = QWidget()
        fila = QHBoxLayout(rango)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(self.desde)
        fila.addWidget(self.hasta)
        self.valor = QStackedWidget()
        self.valor.addWidget(self.valor_texto)
        self.valor.addWidget(self.valor_lista)
        self.valor.addWidget(rango)
        self.valor.addWidget(QLabel("Sin valor que elegir"))
        forma.addRow("Campo", self.campo)
        forma.addRow("Condición", self.operador)
        forma.addRow("Valor", self.valor)
        self.campo.currentIndexChanged.connect(self.cambiar_campo)
        self.operador.currentIndexChanged.connect(self.cambiar_operador)
        self.valor_texto.textChanged.connect(self.cambiar_valor)
        self.valor_lista.itemChanged.connect(self.cambiar_valor)
        self.desde.textChanged.connect(self.cambiar_valor)
        self.hasta.textChanged.connect(self.cambiar_valor)
        return pagina

    def _editor_grupo(self):
        pagina = QWidget()
        forma = QFormLayout(pagina)
        self.grupo_todas = QComboBox()
        self.grupo_todas.addItem("todas", True)
        self.grupo_todas.addItem("alguna", False)
        self.grupo_todas.currentIndexChanged.connect(self.cambiar_grupo)
        forma.addRow("Que cumplan", self.grupo_todas)
        return pagina

    def _editor_partes(self):
        pagina = QWidget()
        forma = QFormLayout(pagina)
        self.partes_tiene = QComboBox()
        self.partes_tiene.addItem("Tiene algún parte", True)
        self.partes_tiene.addItem("No tiene ningún parte", False)
        self.partes_formulario = QComboBox()
        self.partes_formulario.addItem("de cualquier tipo", None)
        for nombre, info in self.formularios.items():
            self.partes_formulario.addItem(info["title"], nombre)
        self.partes_periodo = QComboBox()
        self.partes_periodo.addItem("en cualquier fecha", "cualquiera")
        self.partes_periodo.addItem("en los últimos días…", "ultimos")
        self.partes_periodo.addItem("entre fechas (aaaa-mm-dd)…", "entre")
        self.partes_dias = QSpinBox()
        self.partes_dias.setRange(1, 36600)
        self.partes_desde = QLineEdit()
        self.partes_hasta = QLineEdit()
        self.partes_todas = QComboBox()
        self.partes_todas.addItem("todas", True)
        self.partes_todas.addItem("alguna", False)
        self.partes_ultimo = QCheckBox("Mirar solo el último parte de cada elemento")
        forma.addRow(self.partes_tiene, self.partes_formulario)
        forma.addRow("Periodo", self.partes_periodo)
        forma.addRow("Días", self.partes_dias)
        forma.addRow("Desde", self.partes_desde)
        forma.addRow("Hasta", self.partes_hasta)
        forma.addRow("Que cumplan", self.partes_todas)
        forma.addRow(QLabel("Las condiciones de un bloque se cumplen en el mismo parte."))
        forma.addRow(self.partes_ultimo)
        for control in (self.partes_tiene, self.partes_formulario, self.partes_periodo, self.partes_todas):
            control.currentIndexChanged.connect(self.cambiar_partes)
        self.partes_dias.valueChanged.connect(self.cambiar_partes)
        self.partes_desde.textChanged.connect(self.cambiar_partes)
        self.partes_hasta.textChanged.connect(self.cambiar_partes)
        self.partes_ultimo.toggled.connect(self.cambiar_partes)
        return pagina

    # ------------------------------------------------------------------ árbol

    def _titulo(self, nombre, partes=None):
        campos = self.formularios.get(partes, {}).get("campos") if partes else self.campos
        return next((c["title"] for c in campos or [] if c["name"] == nombre), nombre)

    def _texto(self, nodo):
        if F.es_partes(nodo):
            nombre = self.formularios.get(nodo.get("partes"), {}).get("title") or "cualquier tipo"
            return f"{'Tiene algún' if nodo.get('tiene', True) else 'No tiene ningún'} parte de {nombre}"
        if F.es_grupo(nodo):
            return f"Grupo: que cumplan {'todas' if nodo.get('todas', True) else 'alguna'}"
        resumen = F.frase_del_arbol({"todas": True, "condiciones": [nodo]}, self._titulo)
        return resumen if F.condicion_completa(nodo) else f"{self._titulo(nodo.get('campo'))} {F.etiqueta(nodo.get('op'))} …"

    def repintar(self, elegido=None):
        """Rehace la lista desde el árbol y deja elegido el nodo `elegido`."""
        self.vista.blockSignals(True)
        self.vista.clear()
        seleccion = None
        for nodo in self.arbol["condiciones"]:
            item = QTreeWidgetItem([self._texto(nodo)])
            item.setData(0, ROL_NODO, id(nodo))
            self.vista.addTopLevelItem(item)
            if nodo is elegido:
                seleccion = item
            for hijo in nodo.get("condiciones") or [] if (F.es_grupo(nodo) or F.es_partes(nodo)) else []:
                sub = QTreeWidgetItem([self._texto(hijo)])
                sub.setData(0, ROL_NODO, id(hijo))
                item.addChild(sub)
                if hijo is elegido:
                    seleccion = sub
            item.setExpanded(True)
        self.vista.blockSignals(False)
        if seleccion is not None:
            self.vista.setCurrentItem(seleccion)
        else:
            self.editor.setCurrentIndex(0)
        self.actualizar_frase()

    def actualizar_frase(self):
        self.frase.setText(
            "Se muestran: "
            + F.frase_del_arbol(self.arbol, self._titulo, lambda n: self.formularios.get(n, {}).get("title") or n)
        )

    def _buscar(self, identificador):
        """`(nodo, padre)` del nodo con ese id(); padre None si cuelga de la raíz."""
        for nodo in self.arbol["condiciones"]:
            if id(nodo) == identificador:
                return nodo, None
            for hijo in nodo.get("condiciones") or [] if (F.es_grupo(nodo) or F.es_partes(nodo)) else []:
                if id(hijo) == identificador:
                    return hijo, nodo
        return None, None

    def _actual(self):
        item = self.vista.currentItem()
        return self._buscar(item.data(0, ROL_NODO)) if item else (None, None)

    def _refrescar_actual(self):
        item = self.vista.currentItem()
        nodo, _ = self._actual()
        if item is not None and nodo is not None:
            item.setText(0, self._texto(nodo))
        self.actualizar_frase()

    # ------------------------------------------------------------------ ranuras

    def cambiar_raiz(self):
        self.arbol["todas"] = bool(self.raiz.currentData())
        self.actualizar_frase()

    def anadir_condicion(self):
        nodo, padre = self._actual()
        contenedor = nodo if nodo is not None and (F.es_grupo(nodo) or F.es_partes(nodo)) else padre
        if contenedor is not None and F.es_partes(contenedor):
            campos = self.formularios.get(contenedor.get("partes"), {}).get("campos") or []
        else:
            campos = self.campos
        if not campos:
            return
        nueva = F.condicion_nueva(campos[0]["name"], campos[0]["tipo"])
        (contenedor["condiciones"] if contenedor is not None else self.arbol["condiciones"]).append(nueva)
        self.repintar(nueva)

    def anadir_grupo(self):
        grupo = {"todas": False, "condiciones": [F.condicion_nueva(self.campos[0]["name"], self.campos[0]["tipo"])]}
        self.arbol["condiciones"].append(grupo)
        self.repintar(grupo)

    def anadir_partes(self):
        if not self.formularios:
            return
        bloque = {"partes": next(iter(self.formularios)), "tiene": True, "periodo": None, "ultimo": False,
                  "todas": True, "condiciones": []}
        self.arbol["condiciones"].append(bloque)
        self.repintar(bloque)

    def quitar(self):
        nodo, padre = self._actual()
        if nodo is None:
            return
        (padre["condiciones"] if padre is not None else self.arbol["condiciones"]).remove(nodo)
        self.repintar(padre)

    def elegir(self, *_):
        nodo, padre = self._actual()
        self._cargando = True
        try:
            if nodo is None:
                self.editor.setCurrentIndex(0)
            elif F.es_partes(nodo):
                self._cargar_partes(nodo)
                self.editor.setCurrentIndex(3)
            elif F.es_grupo(nodo):
                self.grupo_todas.setCurrentIndex(0 if nodo.get("todas", True) else 1)
                self.editor.setCurrentIndex(2)
            else:
                self._cargar_condicion(nodo, padre)
                self.editor.setCurrentIndex(1)
        finally:
            self._cargando = False

    def _campos_de(self, padre):
        if padre is not None and F.es_partes(padre):
            return self.formularios.get(padre.get("partes"), {}).get("campos") or []
        return self.campos

    def _cargar_condicion(self, nodo, padre):
        campos = self._campos_de(padre)
        self.campo.clear()
        for c in campos:
            self.campo.addItem(c["title"], c["name"])
        self.campo.setCurrentIndex(max(0, self.campo.findData(nodo.get("campo"))))
        self._cargar_operadores(nodo, campos)
        self._cargar_valor(nodo, campos)

    def _campo_de(self, nodo, campos):
        return next((c for c in campos if c["name"] == nodo.get("campo")), {"tipo": "texto", "valores": []})

    def _cargar_operadores(self, nodo, campos):
        self.operador.clear()
        for op, texto in F.operadores_de(self._campo_de(nodo, campos)["tipo"]):
            self.operador.addItem(texto, op)
        self.operador.setCurrentIndex(max(0, self.operador.findData(nodo.get("op"))))

    def _cargar_valor(self, nodo, campos):
        forma = F.forma_del_valor(nodo.get("op"))
        campo = self._campo_de(nodo, campos)
        valor = nodo.get("valor")
        if forma == "lista":
            self.valor_lista.clear()
            elegidos = set(valor or [])
            for v in campo["valores"] or sorted(elegidos):
                item = QListWidgetItem(v)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if v in elegidos else Qt.CheckState.Unchecked)
                self.valor_lista.addItem(item)
            self.valor.setCurrentIndex(1)
        elif forma == "rango":
            self.desde.setText(str((valor or {}).get("desde") or ""))
            self.hasta.setText(str((valor or {}).get("hasta") or ""))
            self.valor.setCurrentIndex(2)
        elif forma == "ninguno":
            self.valor.setCurrentIndex(3)
        else:
            self.valor_texto.setText("" if valor is None else str(valor))
            self.valor_texto.setPlaceholderText("días" if nodo.get("op") == "ultimos_dias" else "aaaa-mm-dd" if campo["tipo"] == "fecha" else "Valor")
            self.valor.setCurrentIndex(0)

    def cambiar_campo(self):
        if self._cargando:
            return
        nodo, padre = self._actual()
        if nodo is None or F.es_grupo(nodo) or F.es_partes(nodo):
            return
        campos = self._campos_de(padre)
        nombre = self.campo.currentData()
        campo = next((c for c in campos if c["name"] == nombre), None)
        if campo is None:
            return
        nodo.clear()
        nodo.update(F.condicion_nueva(nombre, campo["tipo"]))
        self._cargando = True
        try:
            self._cargar_operadores(nodo, campos)
            self._cargar_valor(nodo, campos)
        finally:
            self._cargando = False
        self._refrescar_actual()

    def cambiar_operador(self):
        if self._cargando:
            return
        nodo, padre = self._actual()
        if nodo is None or F.es_grupo(nodo) or F.es_partes(nodo):
            return
        nuevo = self.operador.currentData()
        nodo["valor"] = F.convertir_valor(nodo.get("valor"), nodo.get("op"), nuevo)
        nodo["op"] = nuevo
        self._cargando = True
        try:
            self._cargar_valor(nodo, self._campos_de(padre))
        finally:
            self._cargando = False
        self._refrescar_actual()

    def cambiar_valor(self, *_):
        if self._cargando:
            return
        nodo, _ = self._actual()
        if nodo is None or F.es_grupo(nodo) or F.es_partes(nodo):
            return
        forma = F.forma_del_valor(nodo.get("op"))
        if forma == "lista":
            nodo["valor"] = [
                self.valor_lista.item(i).text()
                for i in range(self.valor_lista.count())
                if self.valor_lista.item(i).checkState() == Qt.CheckState.Checked
            ]
        elif forma == "rango":
            nodo["valor"] = {"desde": self.desde.text().strip(), "hasta": self.hasta.text().strip()}
        elif forma == "escalar":
            nodo["valor"] = self.valor_texto.text()
        self._refrescar_actual()

    def cambiar_grupo(self):
        if self._cargando:
            return
        nodo, _ = self._actual()
        if nodo is not None and F.es_grupo(nodo):
            nodo["todas"] = bool(self.grupo_todas.currentData())
            self._refrescar_actual()

    def _cargar_partes(self, nodo):
        self.partes_tiene.setCurrentIndex(0 if nodo.get("tiene", True) else 1)
        self.partes_formulario.setCurrentIndex(max(0, self.partes_formulario.findData(nodo.get("partes"))))
        periodo = nodo.get("periodo") or {}
        tipo = "ultimos" if "ultimos_dias" in periodo else "entre" if periodo else "cualquiera"
        self.partes_periodo.setCurrentIndex(self.partes_periodo.findData(tipo))
        self.partes_dias.setValue(int(periodo.get("ultimos_dias") or 30))
        self.partes_desde.setText(periodo.get("desde") or "")
        self.partes_hasta.setText(periodo.get("hasta") or "")
        self.partes_todas.setCurrentIndex(0 if nodo.get("todas", True) else 1)
        self.partes_ultimo.setChecked(bool(nodo.get("ultimo")))
        self._mostrar_periodo(tipo)

    def _mostrar_periodo(self, tipo):
        self.partes_dias.setEnabled(tipo == "ultimos")
        self.partes_desde.setEnabled(tipo == "entre")
        self.partes_hasta.setEnabled(tipo == "entre")

    def cambiar_partes(self, *_):
        if self._cargando:
            return
        nodo, _ = self._actual()
        if nodo is None or not F.es_partes(nodo):
            return
        formulario = self.partes_formulario.currentData()
        if formulario != nodo.get("partes"):
            nodo["condiciones"] = []  # las condiciones eran de otro formulario
        nodo["partes"] = formulario
        nodo["tiene"] = bool(self.partes_tiene.currentData())
        nodo["todas"] = bool(self.partes_todas.currentData())
        nodo["ultimo"] = self.partes_ultimo.isChecked()
        tipo = self.partes_periodo.currentData()
        if tipo == "ultimos":
            nodo["periodo"] = {"ultimos_dias": self.partes_dias.value()}
        elif tipo == "entre":
            nodo["periodo"] = {"desde": self.partes_desde.text().strip(), "hasta": self.partes_hasta.text().strip()}
        else:
            nodo["periodo"] = None
        self._mostrar_periodo(tipo)
        self.repintar(nodo)

    # ------------------------------------------------------------------ aplicar

    def accept(self):
        self.aplicar()
        super().accept()

    def aplicar(self):
        """Pone las condiciones en la URI de la capa; el estilo y la ficha se quedan."""
        uri = parse_uri(self.capa.source())
        uri.filtro = F.limpiar_arbol(self.arbol)
        self.capa.setDataSource(str(uri), self.capa.name(), "geosian", QgsDataProvider.ProviderOptions())
        self.capa.triggerRepaint()
