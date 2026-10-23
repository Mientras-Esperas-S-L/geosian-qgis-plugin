"""«Subir capas de QGIS a este mapa…»: varias capas del proyecto de una vez.

Para empezar un mapa desde QGIS, o añadirle capas que estaban en ficheros aparte. Cada
capa marcada se crea con sus campos (LAD mínimo, como «Crear capa en este mapa…») y sus
elementos, empaquetada como GeoPackage y una detrás de otra en segundo plano
(``ImportarCapas``). Formularios, listas, partes y colores se completan después en la web.
"""

from qgis.core import QgsProject, QgsVectorLayer
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
    lanzar,
    nombres_del_mapa,
    ya_existe,
)

COL_CAPA, COL_NOMBRE, COL_ELEMENTOS, COL_GEOMETRIA, COL_AVISO = range(5)


def capas_del_proyecto():
    """Las capas vectoriales del proyecto que no vienen ya de la aplicación."""
    return [
        capa for capa in QgsProject.instance().mapLayers().values()
        if isinstance(capa, QgsVectorLayer) and capa.providerType() != "geosian"
    ]


class SubirCapasDialog(QDialog):
    def __init__(self, mapa, parent=None, cliente=None):
        super().__init__(parent)
        self.mapa = mapa
        self.elegidas = []
        # Las que ya tiene el mapa: el nombre repetido se ve antes de subir nada.
        self.existentes = nombres_del_mapa(cliente, mapa.get("id")) if cliente else set()
        self.setWindowTitle(f"Subir capas de QGIS a «{mapa.get('name')}»")
        self.setMinimumWidth(760)

        explicacion = QLabel(
            "Marca las capas que quieres subir. Cada una se crea con sus campos y sus elementos, "
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
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)

        marca = QTableWidgetItem(capa.name())
        marca.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        marca.setCheckState(Qt.CheckState.Checked if geometria else Qt.CheckState.Unchecked)
        if geometria is None:
            marca.setFlags(Qt.ItemFlag.ItemIsUserCheckable)  # sin geometría útil no se puede marcar
        self.tabla.setItem(fila, COL_CAPA, marca)
        self.tabla.setItem(fila, COL_NOMBRE, QTableWidgetItem(capa.name()))
        solo_lectura = Qt.ItemFlag.ItemIsEnabled
        avisos = []
        if geometria is None:
            avisos.append("Sin punto, línea ni polígono: no se puede subir.")
        else:
            if capa.name().strip().casefold() in self.existentes:
                avisos.append("Ya hay una capa con este nombre en el mapa: cámbialo.")
            if fuera:
                avisos.append("No se llevan: " + ", ".join(fuera))
        for col, texto in (
            (COL_ELEMENTOS, f"{C.contar_elementos(capa):,}".replace(",", ".")),
            (COL_GEOMETRIA, geometria or "—"),
            (COL_AVISO, " ".join(avisos)),
        ):
            celda = QTableWidgetItem(texto)
            celda.setFlags(solo_lectura)
            self.tabla.setItem(fila, col, celda)
        self.capas.append((capa, geometria, campos, correspondencia))

    def _aceptar(self):
        elegidas, nombres = [], set()
        for fila, (capa, geometria, campos, correspondencia) in enumerate(self.capas):
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
            elegidas.append((capa, {"name": nombre, "geometry_type": geometria, "campos": campos}, correspondencia))
        if not elegidas:
            self.estado.setText("Marca al menos una capa.")
            return
        self.elegidas = elegidas
        self.accept()


def subir_capas(dock, datos_mapa, parent=None):
    """Abre la ventana y, al aceptar, lanza la subida en segundo plano. Devuelve la tarea."""
    conexion, mapa = datos_mapa["conexion"], datos_mapa["mapa"]
    dialogo = SubirCapasDialog(mapa, parent, cliente=connections.client_for(conexion))
    if not dialogo.exec() or not dialogo.elegidas:
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
