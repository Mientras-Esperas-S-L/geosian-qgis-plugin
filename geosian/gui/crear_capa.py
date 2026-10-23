"""«Crear capa en Geosian…»: una capa nueva en un mapa, sin definir sus campos en QGIS.

Dos formas (``core/crear_capa.py`` y la API ``maps/<id>/layers/crear/``):

- **A partir de otra capa de Geosian**: la capa nueva, vacía, con los formularios, partes
  y colores de la elegida, y si se quiere sus vistas.
- **A partir de una capa de QGIS**: con sus campos (nombre, título y tipo) y, si se
  quiere, sus elementos, que suben con el guardado de siempre (todo o nada). Con más de
  ``MAX_ELEMENTOS``, en una tarea de QGIS: se empaquetan en un GeoPackage, suben a trozos y
  el servidor los importa; la capa aparece al terminar (``core/importar_grande.py``).

Lo demás (listas, partes, fotos, colores) se completa en la web. La capa nueva la ve el
grupo de quien la crea y va en la carpeta «Nuevas desde QGIS».
"""

import os
import shutil
import tempfile
import threading
import traceback

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeature,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsMessageLog,
    QgsProject,
    QgsTask,
    QgsVectorLayerFeatureSource,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)

from ..core import connections
from ..core import crear_capa as C
from ..core import importar_grande as I
from ..core.errors import (
    AuthError,
    ForbiddenError,
    GeosianError,
    HttpError,
    NetworkError,
)

PLANTILLA, DE_QGIS = 0, 1
# El nombre de la aplicación en lo que ve el técnico.
APP = "GreenCityControl"


def texto_de_error(exc):
    """Lo que se le dice a quien crea la capa, con qué hacer si se puede."""
    if isinstance(exc, AuthError):
        return ("Tu sesión de GreenCityControl ha caducado. Vuelve a entrar (clic derecho en la conexión del "
                "panel › Volver a entrar) y repite.")
    if isinstance(exc, NetworkError):
        return f"Sin conexión con GreenCityControl: {exc}. Comprueba la red y repite."
    if isinstance(exc, HttpError):
        if exc.status and exc.status >= 500:
            # El cuerpo de un 502 es la página de error del servidor web, no un motivo.
            return f"GreenCityControl no ha podido atenderlo ahora (error {exc.status}). Espera un poco y repite."
        # El motivo, sin el «HTTP 409:» de delante.
        return Exception.__str__(exc)
    return str(exc)


def capas_para_subir():
    """Las capas vectoriales del proyecto que no vienen ya de la aplicación."""
    from qgis.core import QgsVectorLayer

    return [
        capa for capa in QgsProject.instance().mapLayers().values()
        if isinstance(capa, QgsVectorLayer) and capa.providerType() != "geosian"
    ]


def nombres_del_mapa(cliente, map_id):
    """Los nombres de las capas que ya tiene el mapa, en minúsculas.

    Para avisar antes de empaquetar y subir nada. Si no se pueden pedir, vacío: el servidor
    lo vuelve a mirar al crear.
    """
    try:
        return {str(c.get("name") or "").strip().casefold() for c in cliente.layers(map_id)}
    except (GeosianError, AttributeError):
        return set()


def ya_existe(nombre):
    return f"Ya hay una capa «{nombre}» en este mapa. Elige otro nombre."


# Quien entra como administrador crea las capas sin grupo (services/crear_capa.py del backend).
QUIEN_LA_VE = (
    "La verá tu grupo, en la carpeta «Nuevas desde QGIS»; si entras como administrador, solo "
    "los administradores hasta que le asignes un grupo en la web."
)


class CrearCapaDialog(QDialog):
    def __init__(self, conexion, mapa, parent=None):
        super().__init__(parent)
        self.conexion = conexion
        self.mapa = mapa
        self.cliente = connections.client_for(conexion)
        self.capa_creada = None
        # Lo que falló al cargar mapas o capas: manda sobre «elige la plantilla».
        self.error_de_carga = None
        self.subir = False
        # Más de MAX_ELEMENTOS: la capa no se crea aquí, la crea la importación.
        self.grande = None
        self.correspondencia = {}
        self.setWindowTitle(f"Crear capa en «{mapa.get('name')}»")
        self.setMinimumWidth(560)

        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Arbolado 2027")
        formulario = QFormLayout()
        formulario.addRow("Nombre", self.nombre)

        self.forma = QButtonGroup(self)
        self.de_plantilla = QRadioButton("A partir de otra capa de GreenCityControl (sus formularios, partes y colores)")
        self.de_qgis = QRadioButton("A partir de una capa de QGIS (sus campos y, si quieres, sus elementos)")
        self.forma.addButton(self.de_plantilla, PLANTILLA)
        self.forma.addButton(self.de_qgis, DE_QGIS)
        # Si el proyecto tiene capas que llevar, lo normal es crear a partir de una.
        (self.de_qgis if capas_para_subir() else self.de_plantilla).setChecked(True)

        # Plantilla: mapa y capa (por defecto, el mapa en el que se crea).
        self.caja_plantilla = QGroupBox()
        disp = QFormLayout(self.caja_plantilla)
        self.mapa_plantilla = QComboBox()
        self.capa_plantilla = QComboBox()
        # Sin ninguna elegida de entrada: que copiar una capa sea a propósito.
        self.capa_plantilla.setPlaceholderText("Elige la capa que sirve de modelo")
        self.copiar_vistas = QCheckBox("Copiar también sus vistas")
        disp.addRow("Mapa", self.mapa_plantilla)
        disp.addRow("Capa", self.capa_plantilla)
        disp.addRow("", self.copiar_vistas)

        # Desde QGIS: la capa y lo que se va a crear.
        self.caja_qgis = QGroupBox()
        disp = QFormLayout(self.caja_qgis)
        self.capa_qgis = QgsMapLayerComboBox()
        self.capa_qgis.setFilters(QgsMapLayerProxyModel.Filter.VectorLayer)
        self.capa_qgis.setExcludedProviders(["geosian"])
        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.resumen.setTextFormat(Qt.TextFormat.PlainText)
        self.con_elementos = QCheckBox()
        disp.addRow("Capa de QGIS", self.capa_qgis)
        disp.addRow("", self.resumen)
        disp.addRow("", self.con_elementos)

        aviso = QLabel(
            f"{QUIEN_LA_VE} Listas, partes, fotos y colores se completan después en la web de GCC."
        )
        aviso.setWordWrap(True)
        self.estado = QLabel("")
        self.estado.setWordWrap(True)

        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Crear capa")
        self.botones.accepted.connect(self._crear)
        self.botones.rejected.connect(self.reject)

        caja = QVBoxLayout(self)
        caja.addLayout(formulario)
        caja.addWidget(self.de_plantilla)
        caja.addWidget(self.caja_plantilla)
        caja.addWidget(self.de_qgis)
        caja.addWidget(self.caja_qgis)
        caja.addWidget(aviso)
        caja.addWidget(self.estado)
        caja.addWidget(self.botones)

        self.forma.idToggled.connect(self._al_cambiar_forma)
        self.mapa_plantilla.currentIndexChanged.connect(self._cargar_capas_plantilla)
        self.capa_qgis.layerChanged.connect(self._al_cambiar_capa_qgis)
        self._cargar_mapas()
        self._al_cambiar_capa_qgis(self.capa_qgis.currentLayer())
        self._al_cambiar_forma()

    # ------------------------------------------------------------------
    def _al_cambiar_forma(self, *_):
        plantilla = self.forma.checkedId() == PLANTILLA
        self.caja_plantilla.setEnabled(plantilla)
        self.caja_qgis.setEnabled(not plantilla)

    def _cargar_mapas(self):
        try:
            mapas = self.cliente.maps() if self.cliente else []
        except GeosianError as exc:
            self.error_de_carga = f"No se pudieron cargar los mapas. {texto_de_error(exc)}"
            self.estado.setText(self.error_de_carga)
            mapas = []
        mapas = sorted(mapas, key=lambda m: (m.get("id") != self.mapa.get("id"), str(m.get("name") or "").casefold()))
        for mapa in mapas:
            self.mapa_plantilla.addItem(mapa.get("name") or f"Mapa {mapa.get('id')}", mapa)

    def _cargar_capas_plantilla(self, *_):
        self.capa_plantilla.clear()
        mapa = self.mapa_plantilla.currentData()
        if not mapa:
            return
        try:
            capas = self.cliente.layers(mapa["id"])
        except GeosianError as exc:
            self.error_de_carga = f"No se pudieron cargar las capas. {texto_de_error(exc)}"
            self.estado.setText(self.error_de_carga)
            return
        for capa in sorted(capas, key=lambda c: str(c.get("name") or "").casefold()):
            self.capa_plantilla.addItem(capa.get("name") or f"Capa {capa.get('id')}", capa)
        self.capa_plantilla.setCurrentIndex(-1)

    def _al_cambiar_capa_qgis(self, capa):
        self.campos, self.fuera, self.correspondencia = ([], [], {})
        self.geometria = None
        self.total_elementos = 0
        self.motivo = None
        if capa is None:
            self.resumen.setText("No hay capas vectoriales en el proyecto.")
            self.con_elementos.setEnabled(False)
            return
        self.geometria = C.tipo_de_geometria(capa)
        self.campos, self.fuera, self.correspondencia = C.campos_de(capa)
        self.motivo = C.motivo_para_no_subir(capa, self.campos)
        lineas = []
        if self.motivo:
            lineas.append(f"No se puede crear a partir de esta capa. {self.motivo}")
        else:
            lineas.append(f"Geometría: {self.geometria}.")
        if self.campos:
            nombres = [
                c["name"] if c["name"] == c["title"] else f"{c['title']} → {c['name']}" for c in self.campos
            ]
            lineas.append(f"Campos ({len(self.campos)}): " + ", ".join(nombres) + ".")
        else:
            lineas.append("Sin campos: la capa tendrá solo geometría; los campos se añaden en la web.")
        if self.fuera:
            lineas.append("No se llevan (tipo no admitido): " + ", ".join(self.fuera) + ".")
        self.resumen.setText("\n".join(lineas))
        total = self.total_elementos = C.contar_elementos(capa)
        self.con_elementos.setText(f"Subir también sus {total:,} elementos".replace(",", "."))
        self.con_elementos.setEnabled(total > 0)
        self.con_elementos.setChecked(total > 0)
        if total > C.MAX_ELEMENTOS:
            self.con_elementos.setText(
                f"Subir también sus {total:,} elementos, en segundo plano: la capa aparecerá "
                "cuando estén todos dentro".replace(",", ".")
            )

    # ------------------------------------------------------------------
    def _crear(self):
        nombre = self.nombre.text().strip()
        if not nombre:
            self.estado.setText("Ponle un nombre a la capa.")
            return
        if nombre.casefold() in nombres_del_mapa(self.cliente, self.mapa["id"]):
            self.estado.setText(ya_existe(nombre))
            return
        if self.forma.checkedId() == PLANTILLA:
            plantilla = self.capa_plantilla.currentData()
            if not plantilla:
                self.estado.setText(self.error_de_carga or "Elige la capa que sirve de modelo.")
                return
            datos = {"name": nombre, "plantilla": plantilla["id"], "copiar_vistas": self.copiar_vistas.isChecked()}
        else:
            if self.capa_qgis.currentLayer() is None:
                self.estado.setText("Elige una capa de QGIS con geometría de punto, línea o polígono.")
                return
            if self.motivo:
                self.estado.setText(self.motivo)
                return
            datos = {"name": nombre, "geometry_type": self.geometria, "campos": self.campos}
            if self.con_elementos.isChecked() and self.total_elementos > C.MAX_ELEMENTOS:
                # La crea el servidor al importar; aquí no se pide nada.
                self.grande = {**datos, "elementos": self.total_elementos}
                self.accept()
                return

        self.botones.setEnabled(False)
        self.estado.setText("Creando la capa…")
        try:
            self.capa_creada = self.cliente.crear_capa(self.mapa["id"], datos)
        except GeosianError as exc:
            self.estado.setText(f"No se ha creado la capa. {texto_de_error(exc)}")
            return
        finally:
            self.botones.setEnabled(True)
        self.subir = self.forma.checkedId() == DE_QGIS and self.con_elementos.isChecked()
        self.accept()


def subir_elementos(origen, destino, correspondencia):
    """Copia los elementos de ``origen`` (QGIS) a ``destino`` (la capa de Geosian nueva) y
    guarda: un solo lote, todo o nada (más de 300, en segundo plano).

    Devuelve ``(ok, mensaje)``.
    """
    transformacion = QgsCoordinateTransform(origen.crs(), destino.crs(), QgsProject.instance())
    campos = destino.fields()
    multi = QgsWkbTypes.isMultiType(destino.wkbType())
    nuevos, sin_geometria, fuera_de_su_sistema = [], 0, []
    for elemento in origen.getFeatures():
        geometria = QgsGeometry(elemento.geometry())
        if geometria.isNull() or geometria.isEmpty():
            sin_geometria += 1
            continue
        try:
            geometria = C.geometria_para_geosian(geometria, transformacion, multi)
        except QgsCsException:
            fuera_de_su_sistema.append(elemento.id())
            continue
        nuevo = QgsFeature(campos)
        nuevo.setGeometry(geometria)
        for de_qgis, en_geosian in correspondencia.items():
            indice = campos.indexFromName(en_geosian)
            if indice >= 0:
                tipo = origen.fields().field(de_qgis).type()
                nuevo.setAttribute(indice, C.valor_para_geosian(elemento[de_qgis], tipo))
        nuevos.append(nuevo)
    if fuera_de_su_sistema:
        return False, f"No se ha subido nada. {C.fuera_de_su_sistema(fuera_de_su_sistema)}"
    if not nuevos:
        return True, "La capa de QGIS no tiene elementos con geometría."
    if not destino.isEditable():
        destino.startEditing()
    if not destino.addFeatures(nuevos):
        destino.rollBack()
        return False, "QGIS no pudo preparar los elementos."
    if destino.commitChanges():
        return True, f"Subidos {len(nuevos):,} elementos.".replace(",", ".") + saltados(sin_geometria)
    errores = _motivos(destino.commitErrors())
    destino.rollBack()
    return False, f"No se ha subido nada. {errores}"


def saltados(sin_geometria):
    """Lo que no se subió por no tener geometría, para que no parezca que faltan."""
    if not sin_geometria:
        return ""
    if sin_geometria == 1:
        return " Uno sin geometría se ha quedado fuera."
    return f" {sin_geometria:,} sin geometría se han quedado fuera.".replace(",", ".")


def _motivos(errores):
    """Lo que dice Geosian, sin el envoltorio de QGIS («ERROR: … not added», «Provider errors:»)."""
    propios = [
        e.strip() for e in errores
        if e.strip() and not e.strip().startswith("ERROR:") and "Provider errors" not in e
    ]
    return "; ".join(propios or [e.strip() for e in errores if e.strip()])


class ImportarCapas(QgsTask):
    """Empaqueta capas de QGIS, las sube a trozos y espera a que el servidor las importe.

    Una detrás de otra (el servidor admite una importación por persona a la vez), en
    segundo plano: el gestor de tareas de QGIS enseña el avance. Al acabar, añade al
    proyecto las que entraron y dice cuáles no y por qué.
    """

    def __init__(self, dock, conexion, mapa, capas, titulo=None):
        """``capas``: ``[(capa de QGIS, datos para la API, correspondencia de campos)]``."""
        if titulo is None:
            que = f"«{capas[0][1]['name']}»" if len(capas) == 1 else f"{len(capas)} capas"
            titulo = f"Subir {que} a «{mapa.get('name')}»"
        super().__init__(titulo, QgsTask.Flag.CanCancel)
        self.dock = dock
        self.conexion = conexion
        self.mapa = mapa
        # La capa y el proyecto no se tocan desde el hilo de la tarea.
        self.capas = [
            {"fuente": QgsVectorLayerFeatureSource(origen),
             # Los contó ya la ventana: con un WFS, contar otra vez es descargarlo otra vez.
             "total": datos.get("elementos") if datos.get("elementos") is not None else C.contar_elementos(origen),
             "datos": datos, "correspondencia": correspondencia}
            for origen, datos, correspondencia in capas
        ]
        self.contexto = QgsProject.instance().transformContext()
        # Una por capa: {"nombre", "final" (estado del servidor) o None, "error" o None}.
        self.resultados = []

    def _fase(self, desde, hasta):
        return lambda parte: self.setProgress(desde + (hasta - desde) * parte)

    def run(self):
        # El servidor admite una importación por persona a la vez: la tarea que llega con
        # otra en marcha espera su turno, en vez de empaquetar y fallar al abrir la subida.
        while not _UNA_A_LA_VEZ.acquire(timeout=0.5):
            if self.isCanceled():
                return False
        try:
            return self._subir_todas()
        finally:
            _UNA_A_LA_VEZ.release()

    def _subir_todas(self):
        cliente = connections.client_for(self.conexion)
        n = len(self.capas)
        for i, capa in enumerate(self.capas):
            if self.isCanceled():
                break
            base, ancho = 100 * i / n, 100 / n
            resultado = {"nombre": capa["datos"]["name"], "final": None, "error": None, "sin_geometria": 0}
            self.resultados.append(resultado)
            carpeta = tempfile.mkdtemp(prefix="geosian-importar-")
            try:
                ruta = os.path.join(carpeta, "capa.gpkg")
                escritos, resultado["sin_geometria"] = I.empaquetar(
                    capa["fuente"], capa["datos"]["campos"], capa["correspondencia"], capa["datos"]["geometry_type"],
                    ruta, avance=self._fase(base, base + ancho * 0.3), cancelado=self.isCanceled,
                    total=capa["total"], contexto=self.contexto,
                )
                datos = {**capa["datos"], "elementos": escritos}
                subida = I.subir(cliente, self.mapa["id"], datos, ruta,
                                 avance=self._fase(base + ancho * 0.3, base + ancho * 0.6), cancelado=self.isCanceled)
                resultado["final"] = I.esperar(cliente, self.mapa["id"], subida["id"],
                                               avance=self._fase(base + ancho * 0.6, base + ancho), cancelado=self.isCanceled)
                if resultado["final"]["estado"] != "hecha":
                    resultado["error"] = resultado["final"].get("error") or "no se sabe por qué"
            except I.Cancelado:
                resultado["error"] = "cancelada"
                break
            except (I.NoSePuede, GeosianError) as exc:
                resultado["error"] = texto_de_error(exc)
                # Sin permiso o sin sesión, las demás fallarían igual tras empaquetarlas.
                if isinstance(exc, (AuthError, ForbiddenError)):
                    break
            except Exception as exc:
                QgsMessageLog.logMessage(traceback.format_exc(), APP, Qgis.Critical)
                resultado["error"] = f"fallo inesperado ({type(exc).__name__}: {exc}); el detalle está en el registro de mensajes"
            finally:
                shutil.rmtree(carpeta, ignore_errors=True)
        return bool(self.resultados) and all(r["error"] is None for r in self.resultados) and len(self.resultados) == n

    def _hechas(self):
        return [r for r in self.resultados if r["error"] is None and r["final"]]

    def finished(self, ok):
        _EN_MARCHA.discard(self)
        hechas = self._hechas()
        if hechas:
            # Una excepción aquí no llegaría a nadie y se perdería el aviso: las capas ya
            # están en el servidor, así que se dice y se sigue.
            try:
                self._abrir(hechas)
            except Exception as exc:
                QgsMessageLog.logMessage(traceback.format_exc(), APP, Qgis.Warning)
                self.dock.iface.messageBar().pushWarning(
                    APP, f"Las capas están en {APP}, pero no se han podido abrir en QGIS. "
                    f"{texto_de_error(exc)} Ábrelas desde el panel."
                )
        self._avisar(ok, hechas)

    def _abrir(self, hechas):
        """Añade al proyecto las capas que entraron y las enseña en el árbol del panel."""
        cliente = connections.client_for(self.conexion)
        cliente.forget_layers()
        capas = {c.get("id"): c for c in cliente.layers(self.mapa["id"])}
        for r in hechas:
            capa = capas.get(r["final"]["capa_id"])
            if capa is not None:
                self.dock.añadir_capa({"conexion": self.conexion, "mapa": self.mapa, "capa": capa})
        # Las nuevas, también en el árbol del panel si el mapa está desplegado.
        if hasattr(self.dock, "refrescar_mapa"):
            self.dock.refrescar_mapa(self.conexion, self.mapa["id"])

    def _avisar(self, ok, hechas):
        barra = self.dock.iface.messageBar()
        fallidas = [r for r in self.resultados if r["error"] is not None]
        if ok:
            fuera = saltados(sum(r["sin_geometria"] for r in hechas))
            if len(hechas) == 1:
                barra.pushSuccess(APP, f"Subida «{hechas[0]['nombre']}» a «{self.mapa.get('name')}».{fuera}")
            else:
                barra.pushSuccess(APP, f"Subidas las {len(hechas)} capas a «{self.mapa.get('name')}».{fuera}")
            return
        partes = [f"«{r['nombre']}»: {r['error']}" for r in fallidas if r["error"] != "cancelada"]
        if self.isCanceled() or any(r["error"] == "cancelada" for r in fallidas):
            partes.append("se canceló; las que faltaban no se han subido")
        elif len(self.resultados) < len(self.capas):
            partes.append("las demás no se han intentado")
        barra.pushWarning(APP, f"Subidas {len(hechas)} de {len(self.capas)} capas. " + "; ".join(partes) + ".")


class ImportarCapaGrande(ImportarCapas):
    """Una sola capa (la de «Crear capa en este mapa…» con más de ``MAX_ELEMENTOS``)."""

    def __init__(self, dock, conexion, mapa, origen, datos, correspondencia):
        super().__init__(dock, conexion, mapa, [(origen, datos, correspondencia)],
                         titulo=f"Importar «{datos['name']}» en {APP}")
        self.datos = datos

    @property
    def final(self):
        return self.resultados[0]["final"] if self.resultados else None

    @property
    def error(self):
        error = self.resultados[0]["error"] if self.resultados else None
        return None if error == "cancelada" else error

    def _avisar(self, ok, hechas):
        barra = self.dock.iface.messageBar()
        nombre = self.datos["name"]
        if ok:
            total = (self.final.get("progreso") or {}).get("total") or 0
            barra.pushSuccess(
                APP, f"«{nombre}» importada con sus {total:,} elementos.".replace(",", ".")
                + saltados(self.resultados[0]["sin_geometria"])
            )
        elif self.isCanceled() or (self.resultados and self.resultados[0]["error"] == "cancelada"):
            barra.pushInfo(APP, f"Importación de «{nombre}» cancelada: no se ha creado nada.")
        else:
            barra.pushWarning(APP, f"No se ha creado «{nombre}». {self.error or 'no se sabe por qué'}")


# Las tareas en marcha: sin una referencia, Python las recoge antes de que acaben.
_EN_MARCHA = set()
_UNA_A_LA_VEZ = threading.Lock()


def lanzar(dock, tarea, mensaje):
    """Pone en marcha una subida y lo dice; si ya hay otra, que va detrás."""
    if _EN_MARCHA:
        mensaje += " Va detrás de la subida que ya está en marcha."
    _EN_MARCHA.add(tarea)
    QgsApplication.taskManager().addTask(tarea)
    dock.iface.messageBar().pushInfo(APP, mensaje)


def crear_capa(dock, datos_mapa, parent=None):
    """Abre el diálogo y, al aceptar, añade la capa al proyecto (y sube sus elementos)."""
    conexion, mapa = datos_mapa["conexion"], datos_mapa["mapa"]
    dialogo = CrearCapaDialog(conexion, mapa, parent)
    if not dialogo.exec():
        return None
    if dialogo.grande:
        tarea = ImportarCapaGrande(
            dock, conexion, mapa, dialogo.capa_qgis.currentLayer(), dialogo.grande, dialogo.correspondencia
        )
        lanzar(
            dock, tarea,
            f"Importando «{dialogo.grande['name']}» en segundo plano; la verás al terminar. "
            "El avance está en la barra de tareas de abajo.",
        )
        return tarea
    if not dialogo.capa_creada:
        return None
    capa = dict(dialogo.capa_creada)
    # Una capa vacía no trae tipos en los metadatos: los de su definición de campos.
    tipos = {"Point": "points", "MultiPoint": "multi_points", "MultiLineString": "multi_lines",
             "MultiPolygon": "multi_polygons"}
    capa["tile_metadata"] = {"geometry_types": [tipos[t] for t in capa.get("geometry_types") or [] if t in tipos]}
    añadidas = dock.añadir_capa({"conexion": conexion, "mapa": mapa, "capa": capa})
    if dialogo.subir and añadidas:
        ok, mensaje = subir_elementos(dialogo.capa_qgis.currentLayer(), añadidas[0], dialogo.correspondencia)
        if ok:
            dock.iface.messageBar().pushSuccess(APP, f"«{capa.get('name')}»: {mensaje}")
        else:
            # La capa ya existe en el servidor: que no parezca que no se creó nada.
            dock.iface.messageBar().pushWarning(
                APP, f"La capa «{capa.get('name')}» se ha creado, pero vacía. {mensaje} "
                "Puedes pegarle los elementos en QGIS y guardar.",
            )
    elif añadidas:
        dock.iface.messageBar().pushSuccess(
            "GreenCityControl",
            f"Capa «{capa.get('name')}» creada. Sus formularios, partes y colores se completan en la web.",
        )
    if not añadidas:
        QMessageBox.warning(parent, "GreenCityControl", "La capa se ha creado, pero no se pudo abrir en QGIS.")
    return añadidas
