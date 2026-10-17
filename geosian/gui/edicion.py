"""Engancha la edición de las capas de Geosian a QGIS.

El proveedor no ve la capa, y el lote necesita lo pendiente de la capa entero
antes de la primera escritura (``provider/edicion.py``). Aquí se conectan las
señales de cada capa de Geosian del proyecto: al empezar a editar, al confirmar
y al descartar.
"""

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QTimer

_vigilando = {"activo": False}


def preguntar_retirada(capa, cuantos):
    """¿Seguir con una confirmación que retira ``cuantos`` elementos?

    Suprimir en QGIS no borra en Geosian: retira. Se dice con esas palabras antes
    de hacerlo. Las pruebas la sustituyen, porque el diálogo esperaría a alguien.
    """
    from qgis.PyQt.QtWidgets import QMessageBox

    elementos = "un elemento" if cuantos == 1 else f"{cuantos} elementos"
    respuesta = QMessageBox.question(
        None,
        "Retirar en Geosian",
        f"Vas a retirar {elementos} de «{capa.name()}».\n\n"
        "En Geosian no se borran: pasan a «no disponible», quedan en su historial y se "
        "pueden recuperar desde la web.\n\n¿Seguir?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return respuesta == QMessageBox.StandardButton.Yes


MIO = "mio"
GEOSIAN = "geosian"


def preguntar_conflictos(capa, conflictos):
    """Qué hacer con cada elemento que otro tocó: ``{id: MIO | GEOSIAN}`` o ``None``.

    Las pruebas la sustituyen, porque el diálogo esperaría a alguien.
    """
    dialogo = dialogo_de_conflictos(capa, conflictos)
    if not dialogo.exec():
        return None
    return dialogo.decisiones()


def resolver_conflictos(capa, proveedor, conflictos, decisiones):
    """Aplica lo elegido. Lo pendiente sigue pendiente: hay que volver a guardar.

    - Lo mío: la próxima confirmación se da por enterada de la versión de Geosian
      y la pisa. No se puede con un elemento que otro ha retirado.
    - Lo de Geosian: lo que hay ahora en Geosian vuelve a la capa y mis cambios de
      ese elemento se quedan sin efecto (no se mandan). Una retirada mía de ese
      elemento no se puede deshacer desde aquí: se deshace con «Deshacer».

    Devuelve lo que no se pudo aplicar, para decirlo.
    """
    buffer = capa.editBuffer()
    por_id = {c["id"]: c for c in conflictos}
    avisos = []
    a_geosian = []
    for fid, decision in decisiones.items():
        choque = por_id.get(fid)
        if choque is None:
            continue
        retirado = choque.get("object_status") not in (None, "disponible")
        if decision == MIO:
            if retirado:
                avisos.append(f"{fid}: lo han retirado; no se puede guardar encima")
                continue
            proveedor.sobrescribir(fid, choque.get("updated_at"))
        elif decision == GEOSIAN:
            a_geosian.append(fid)

    if a_geosian:
        traidos = proveedor.traer_de_geosian(a_geosian)
        cambios = buffer.changedAttributeValues()
        geometrias = buffer.changedGeometries()
        for fid in a_geosian:
            registro = traidos.get(fid) or proveedor.get_cached(fid)
            if fid in buffer.deletedFeatureIds():
                avisos.append(f"{fid}: tu retirada sigue pendiente; deshazla con «Deshacer»")
            if registro is None:
                continue
            for indice in cambios.get(fid, {}):
                capa.changeAttributeValue(fid, indice, registro.attributes[indice])
            if fid in geometrias and registro.geometry is not None:
                capa.changeGeometry(fid, registro.geometry)
    return avisos


def _al_conflicto(capa, proveedor, conflictos):
    """Tras un 409: el diálogo, cuando QGIS haya terminado de confirmar."""
    from qgis.PyQt.QtCore import QTimer

    def mostrar():
        from qgis.PyQt import sip

        if sip.isdeleted(capa) or not capa.isEditable():
            return
        decisiones = preguntar_conflictos(capa, conflictos)
        if not decisiones:
            return
        avisos = resolver_conflictos(capa, proveedor, conflictos, decisiones)
        _avisar(capa, avisos)

    QTimer.singleShot(0, mostrar)


def _al_encolar(capa, total):
    try:
        from qgis.utils import iface
    except ImportError:
        iface = None
    if iface is None:
        return
    cuantos = f"los {total:,} cambios".replace(",", ".") if total else "los cambios"
    iface.messageBar().pushInfo(
        "Geosian",
        f"«{capa.name()}»: Geosian aplica {cuantos} en segundo plano, todos o ninguno. "
        "Puede tardar unos minutos.",
    )


def _avisar(capa, avisos):
    try:
        from qgis.utils import iface
    except ImportError:
        iface = None
    if iface is None:
        return
    texto = f"Conflictos resueltos: vuelve a guardar «{capa.name()}»."
    if avisos:
        texto += " " + "; ".join(avisos) + "."
    iface.messageBar().pushInfo("Geosian", texto)


def dialogo_de_conflictos(capa, conflictos):
    """Una fila por elemento que otro tocó: quién, cuándo y qué hacer con él.

    El ``QDialog`` lleva ``decisiones()`` (``{id: MIO | GEOSIAN}``) y ``combos``.
    """
    from qgis.PyQt.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QLabel,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
    )

    dialogo = QDialog()
    dialogo.setWindowTitle("Otros han cambiado elementos que estás editando")
    caja = QVBoxLayout(dialogo)
    caja.addWidget(QLabel(
        f"En «{capa.name()}» no se ha guardado nada. Alguien cambió estos elementos "
        "después de que los leyeras. Elige qué hacer con cada uno y vuelve a guardar."
    ))
    tabla = QTableWidget(len(conflictos), 4)
    tabla.setHorizontalHeaderLabels(["Elemento", "Quién", "Cuándo", "Qué hacer"])
    combos = {}
    for fila, choque in enumerate(conflictos):
        quien = choque.get("updated_by") or {}
        retirado = choque.get("object_status") not in (None, "disponible")
        tabla.setItem(fila, 0, QTableWidgetItem(str(choque["id"]) + (" (retirado)" if retirado else "")))
        tabla.setItem(fila, 1, QTableWidgetItem(quien.get("nombre") or quien.get("username") or "—"))
        tabla.setItem(fila, 2, QTableWidgetItem(_cuando(choque.get("updated_at"))))
        combo = QComboBox()
        combo.addItem("Quedarme con lo de Geosian (descartar lo mío)", GEOSIAN)
        if not retirado:
            combo.addItem("Sobrescribir con lo mío", MIO)
        tabla.setCellWidget(fila, 3, combo)
        combos[choque["id"]] = combo
    tabla.resizeColumnsToContents()
    caja.addWidget(tabla)
    botones = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    botones.accepted.connect(dialogo.accept)
    botones.rejected.connect(dialogo.reject)
    caja.addWidget(botones)
    dialogo.decisiones = lambda: {fid: combo.currentData() for fid, combo in combos.items()}
    dialogo.combos = combos
    return dialogo


def _cuando(iso):
    """La hora de un ``updated_at`` (ISO con zona) en la hora del equipo."""
    from qgis.PyQt.QtCore import QDateTime, Qt

    fecha = QDateTime.fromString(str(iso or ""), Qt.DateFormat.ISODateWithMs)
    if not fecha.isValid():
        return str(iso or "")
    return fecha.toLocalTime().toString("dd/MM/yyyy HH:mm")


def _antes_de_confirmar(capa, proveedor):
    buffer = capa.editBuffer()
    bajas = [fid for fid in buffer.deletedFeatureIds() if fid >= 0]
    if bajas and not preguntar_retirada(capa, len(bajas)):
        proveedor.cancelar_lote(
            "No se ha guardado nada: has cancelado la retirada. Los cambios siguen pendientes."
        )
        return
    proveedor.preparar_lote(buffer)


def enganchar(capa):
    """Conecta las señales de edición de ``capa`` con su proveedor. Es idempotente."""
    if capa is None or capa.providerType() != "geosian" or not capa.isValid():
        return False
    if capa.property("geosian_edicion"):
        return True
    if not hasattr(capa.dataProvider(), "preparar_lote"):
        return False

    # El proveedor se busca en cada señal: al cambiar el origen de la capa (filtro de
    # partes, reconexión) QGIS le pone uno nuevo y el de antes ya no confirma nada.
    capa.editingStarted.connect(lambda: capa.dataProvider().empezar_edicion())
    capa.beforeCommitChanges.connect(lambda *_: _antes_de_confirmar(capa, capa.dataProvider()))
    capa.afterCommitChanges.connect(lambda: capa.dataProvider().olvidar_lote())
    capa.afterRollBack.connect(lambda: capa.dataProvider().olvidar_lote())
    capa.editingStopped.connect(lambda: capa.dataProvider().terminar_edicion())
    capa.dataSourceChanged.connect(lambda *_: _avisos_del_proveedor(capa))
    _avisos_del_proveedor(capa)
    capa.setProperty("geosian_edicion", True)
    # Si QGIS se cerró esperando la respuesta de un guardado, decir cómo acabó.
    QTimer.singleShot(0, lambda: _lote_sin_respuesta(capa))
    return True


def _lote_sin_respuesta(capa):
    try:
        proveedor = capa.dataProvider()
        estado = proveedor.revisar_lote_sin_respuesta() if proveedor is not None else None
    except RuntimeError:  # la capa ya no existe
        return
    if estado is None:
        return
    que, hora = estado
    textos = {
        "entro": "sí entró en Geosian: lo que ves en la capa ya lo incluye",
        "no_consta": "no entró en Geosian: no se guardó nada",
        "en_curso": "aún se está aplicando en Geosian; recarga la capa en un rato",
    }
    if que not in textos:
        return
    _mensaje(f"«{capa.name()}»: el guardado del {hora}, que se quedó sin respuesta, {textos[que]}.")


def _mensaje(texto):
    try:
        from qgis.utils import iface
    except ImportError:
        iface = None
    if iface is not None:
        iface.messageBar().pushInfo("Geosian", texto)


def _avisos_del_proveedor(capa):
    """A quién avisa el proveedor de la capa de un conflicto o de un lote en cola."""
    proveedor = capa.dataProvider()
    if not hasattr(proveedor, "preparar_lote"):
        return
    proveedor.al_conflicto = lambda conflictos: _al_conflicto(capa, proveedor, conflictos)
    proveedor.al_encolar = lambda total: _al_encolar(capa, total)


def _al_anadir(capas):
    for capa in capas:
        enganchar(capa)


def vigilar_proyecto():
    """Engancha las capas que ya hay y las que se añadan."""
    if _vigilando["activo"]:
        return
    for capa in QgsProject.instance().mapLayers().values():
        enganchar(capa)
    QgsProject.instance().layersAdded.connect(_al_anadir)
    _vigilando["activo"] = True


def dejar_de_vigilar():
    if _vigilando["activo"]:
        try:
            QgsProject.instance().layersAdded.disconnect(_al_anadir)
        except TypeError:
            pass
        _vigilando["activo"] = False
