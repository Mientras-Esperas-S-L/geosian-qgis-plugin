"""«Subir capas de QGIS a este mapa…»: varias capas del proyecto de una vez.

Para empezar un mapa desde QGIS, o añadirle capas que estaban en ficheros aparte. Cada
capa marcada se crea con sus campos (LAD mínimo, como «Crear capa en este mapa…») y sus
elementos, empaquetada como GeoPackage y una detrás de otra en segundo plano
(``ImportarCapas``). Formularios, listas, partes y colores se completan después en la web.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core import connections
from ..core import crear_capa as C
from .crear_capa import (
    APP,
    QUIEN_LA_VE,
    ImportarCapas,
    capas_para_subir,
    lanzar,
    liberar_cupo,
    nombres_del_mapa,
    ya_existe,
)

COL_CAPA, COL_NOMBRE, COL_ELEMENTOS, COL_GEOMETRIA, COL_AVISO = range(5)


capas_del_proyecto = capas_para_subir


class SubirCapasDialog(QDialog):
    def __init__(self, mapa, parent=None, cliente=None, marcadas=None):
        """``marcadas``: los id de las capas que salen marcadas (las seleccionadas en el panel
        de capas); None, todas las que se pueden subir."""
        super().__init__(parent)
        self.mapa = mapa
        self.marcadas = marcadas
        self.elegidas = []
        # Las que ya tiene el mapa: el nombre repetido se ve antes de subir nada.
        self.existentes = nombres_del_mapa(cliente, mapa.get("id")) if cliente else set()
        self.setWindowTitle(f"Subir capas de QGIS a «{mapa.get('name')}»")
        self.setMinimumWidth(760)

        explicacion = QLabel(
            "Marca las capas que quieres subir (si tenías algunas seleccionadas en el panel de "
            "capas, salen marcadas solo esas). Cada una se crea con sus campos y sus elementos, "
            f"una detrás de otra en segundo plano; aparecen en {APP} cuando han entrado enteras. "
            f"{QUIEN_LA_VE} Formularios, listas, partes y colores se completan después en la web."
        )
        explicacion.setWordWrap(True)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Capa de QGIS", f"Nombre en {APP}", "Elementos", "Geometría", "Aviso"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setSectionResizeMode(COL_NOMBRE, QHeaderView.ResizeMode.Stretch)
        cabecera.setSectionResizeMode(COL_AVISO, QHeaderView.ResizeMode.Stretch)

        self.capas = []
        for capa in sorted(capas_del_proyecto(), key=lambda c: c.name().casefold()):
            self._fila(capa)

        self.estado = QLabel("" if self.capas else "No hay capas vectoriales en el proyecto.")
        self.estado.setWordWrap(True)
        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Subir capas")
        self.botones.accepted.connect(self._aceptar)
        self.botones.rejected.connect(self.reject)

        caja = QVBoxLayout(self)
        caja.addWidget(explicacion)
        caja.addWidget(self.tabla)
        caja.addWidget(self.estado)
        caja.addWidget(self.botones)

    def _fila(self, capa):
        geometria = C.tipo_de_geometria(capa)
        campos, fuera, correspondencia = C.campos_de(capa)
        motivo = C.motivo_para_no_subir(capa, campos)
        total = C.contar_elementos(capa)
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)

        marca = QTableWidgetItem(capa.name())
        marca.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        marcada = motivo is None and (self.marcadas is None or capa.id() in self.marcadas)
        marca.setCheckState(Qt.CheckState.Checked if marcada else Qt.CheckState.Unchecked)
        if motivo:
            marca.setFlags(Qt.ItemFlag.ItemIsUserCheckable)  # no se puede subir: no se puede marcar
        self.tabla.setItem(fila, COL_CAPA, marca)
        self.tabla.setItem(fila, COL_NOMBRE, QTableWidgetItem(capa.name()))
        solo_lectura = Qt.ItemFlag.ItemIsEnabled
        avisos = []
        if motivo:
            avisos.append(f"No se puede subir. {motivo}")
        else:
            if capa.name().strip().casefold() in self.existentes:
                avisos.append("Ya hay una capa con este nombre en el mapa: cámbialo.")
            if fuera:
                avisos.append("No se llevan: " + ", ".join(fuera))
        for col, texto in (
            (COL_ELEMENTOS, f"{total:,}".replace(",", ".")),
            (COL_GEOMETRIA, geometria or "—"),
            (COL_AVISO, " ".join(avisos)),
        ):
            celda = QTableWidgetItem(texto)
            celda.setFlags(solo_lectura)
            self.tabla.setItem(fila, col, celda)
        self.capas.append((capa, geometria, campos, correspondencia, total))

    def _aceptar(self):
        elegidas, nombres = [], set()
        for fila, (capa, geometria, campos, correspondencia, total) in enumerate(self.capas):
            if self.tabla.item(fila, COL_CAPA).checkState() != Qt.CheckState.Checked:
                continue
            nombre = self.tabla.item(fila, COL_NOMBRE).text().strip()
            if not nombre:
                self.estado.setText(f"Ponle nombre a «{capa.name()}».")
                return
            if nombre.casefold() in nombres:
                self.estado.setText(f"Hay dos capas con el nombre «{nombre}»: cambia uno.")
                return
            if nombre.casefold() in self.existentes:
                self.estado.setText(ya_existe(nombre))
                return
            nombres.add(nombre.casefold())
            datos = {"name": nombre, "geometry_type": geometria, "campos": campos, "elementos": total}
            elegidas.append((capa, datos, correspondencia))
        if not elegidas:
            self.estado.setText("Marca al menos una capa.")
            return
        self.elegidas = elegidas
        self.accept()


def subir_capas(dock, datos_mapa, parent=None):
    """Abre la ventana y, al aceptar, lanza la subida en segundo plano. Devuelve la tarea."""
    conexion, mapa = datos_mapa["conexion"], datos_mapa["mapa"]
    try:
        # Sin ninguna seleccionada, todas: que no salga la ventana vacía de marcas.
        marcadas = {capa.id() for capa in dock.iface.layerTreeView().selectedLayers()} or None
    except AttributeError:
        marcadas = None
    cliente = connections.client_for(conexion)
    dialogo = SubirCapasDialog(mapa, parent, cliente=cliente, marcadas=marcadas)
    if not dialogo.exec() or not dialogo.elegidas:
        return None
    if cliente is not None and not liberar_cupo(parent, cliente, mapa["id"]):
        return None
    tarea = ImportarCapas(dock, conexion, mapa, dialogo.elegidas)
    lanzar(
        dock, tarea,
        (f"Subiendo «{dialogo.elegidas[0][1]['name']}»" if len(dialogo.elegidas) == 1
         else f"Subiendo {len(dialogo.elegidas)} capas")
        + f" a «{mapa.get('name')}» en segundo plano; aparecerán al terminar. "
        "El avance está en la barra de tareas de abajo.",
    )
    return tarea
