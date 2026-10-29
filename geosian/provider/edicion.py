"""Escribir en Geosian desde QGIS: el lote de una confirmación, todo o nada.

QGIS no confirma de una vez: llama al proveedor por partes (cambios, bajas, altas)
y quita de lo pendiente cada parte que sale bien. Para que en Geosian entre todo o
nada:

- Al empezar a confirmar (``beforeCommitChanges``), ``gui/edicion.py`` le da al
  proveedor una foto de lo pendiente (``editBuffer()``): :meth:`preparar_lote`.
- La **primera** llamada de escritura de QGIS manda el lote entero a
  ``/geodata/confirmar/``. Si falla, devuelve ``False`` y QGIS lo deja todo pendiente.
- Las siguientes no escriben: dan lo suyo por hecho.

Cada cambio va con la versión del elemento que se editó (``updated_at_iso`` al
leerlo). La versión se fija la primera vez que el proveedor ve el elemento durante
la edición y no se mueve hasta confirmar o descartar: una recarga a mitad de la
edición traería la versión nueva y el conflicto no saltaría.

Lo comprobó ``tests/test_lote_qgis.py`` en QGIS 3.34 y 4.
"""

import json
import math
import time
import traceback
import uuid

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsVectorDataProvider,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QEventLoop, QTime, QTimer, QVariant

from ..core import adjuntos as A
from ..core import lotes_sin_respuesta as pendientes
from ..core import schema as S
from ..core.errors import (
    ConflictError,
    ForbiddenError,
    GeosianError,
    HttpError,
    LoteIncierto,
    NetworkError,
)

# Lo que en las propiedades de un elemento pone siempre Geosian (sus claves
# reservadas), aunque el esquema declare un atributo con ese nombre: el valor que
# ve QGIS es el del sistema, y el servidor no deja escribirlo. «id» no está porque
# el esquema que lo declara sale en QGIS como «attr__id».
DE_GEOSIAN = frozenset({
    "id", "object_id", "object_status", "geometry_type", "created_at", "updated_at",
    "updated_at_iso", "longitud", "latitud", "in_succession_group", "additional_info",
    "_thumbnail", "nfc_uuid", "spatial_history_active_id",
})


class Edicion:
    """Lo que el proveedor necesita para escribir. Se mezcla en ``GeosianProvider``.

    Usa del proveedor: ``_cache``, ``_fields``, ``_attr_map``, ``_uri``, ``_crs``,
    ``_client``, ``_permisos``, ``_lock`` y ``_store``.
    """

    def _iniciar_edicion(self):
        # Versión de cada elemento al empezar a editarlo; None fuera de la edición.
        self._base = None
        # La foto de lo pendiente y lo que respondió el servidor a ese lote.
        self._foto = None
        self._hecho = None
        # Los choques del último 409 y a quién avisar (gui/edicion.py abre el diálogo).
        self.conflictos = []
        self.al_conflicto = None
        # A quién decir que el lote va a segundo plano en Geosian (gui/edicion.py).
        self.al_encolar = None
        # (huella, lote_id) del último lote del que no se supo si entró: si se vuelve
        # a guardar lo mismo, va con el mismo identificador y Geosian no lo repite.
        self._incierto = None

    # ------------------------------------------------------------------
    # Lo que se puede hacer
    # ------------------------------------------------------------------

    def _capacidades_de_escritura(self):
        """Las capacidades de escritura que permite el servidor para esta capa, en lista.

        En lista y no combinadas: en QGIS 4 son un tipo propio que no se mezcla con un
        entero, y devolver un ``0`` desde ``capabilities()`` tumba QGIS.
        """
        if not self._valid or self._uri.info_name or not isinstance(self._permisos, dict):
            return []
        capacidades = []
        if self._permisos.get("can_create"):
            capacidades.append(QgsVectorDataProvider.AddFeatures)
        if self._permisos.get("can_retire"):
            # Suprimir en QGIS es retirar en Geosian: pasa a «no disponible», no se borra.
            capacidades.append(QgsVectorDataProvider.DeleteFeatures)
        if self._permisos.get("can_update"):
            capacidades += [
                QgsVectorDataProvider.ChangeAttributeValues,
                QgsVectorDataProvider.ChangeGeometries,
                # Atributos y geometría del mismo elemento en una llamada.
                QgsVectorDataProvider.ChangeFeatures,
            ]
        return capacidades

    # ------------------------------------------------------------------
    # Ciclo de la edición (lo engancha gui/edicion.py)
    # ------------------------------------------------------------------

    def empezar_edicion(self):
        with self._lock:
            self._base = {fid: registro.version for fid, registro in self._cache.items()}
        self._foto = None
        self._hecho = None

    def terminar_edicion(self):
        self._base = None
        self._foto = None
        self._hecho = None

    def olvidar_lote(self):
        self._foto = None
        self._hecho = None

    def _anotar_version(self, fid, version):
        """Lo llama ``_store``: la versión de un elemento que se ve por primera vez."""
        if self._base is not None and fid not in self._base:
            self._base[fid] = version

    def version_base(self, fid):
        if self._base is not None and fid in self._base:
            return self._base[fid]
        registro = self._cache.get(fid)
        return registro.version if registro is not None else None

    # ------------------------------------------------------------------
    # El lote
    # ------------------------------------------------------------------

    def cancelar_lote(self, motivo):
        """La confirmación no sigue: la primera escritura lo dice sin llamar al servidor."""
        self._hecho = None
        self._foto = {"lote": None, "error": motivo}

    def preparar_lote(self, buffer):
        """La foto de lo pendiente, en ``beforeCommitChanges``.

        Si algo no se puede mandar (un campo de solo lectura, un elemento sin
        versión), la foto queda con el motivo y la primera escritura lo dice sin
        llamar al servidor.
        """
        self._hecho = None
        try:
            self._foto = {"lote": self._lote_de(buffer), "error": None}
        except _NoSePuede as exc:
            self._foto = {"lote": None, "error": str(exc)}
        except Exception as exc:
            # Esto corre dentro de la señal de QGIS: una excepción que se escapa
            # cierra QGIS de golpe. Mejor no guardar y decirlo.
            self.log_error(f"Al preparar el lote: {traceback.format_exc()}")
            self._foto = {
                "lote": None,
                "error": f"GreenCityControl: no se ha guardado nada por un fallo del complemento ({exc}). "
                "Los cambios siguen pendientes.",
            }

    def _lote_de(self, buffer):
        # Un alta editada antes de confirmar (id negativo) va con el alta.
        atributos = {fid: v for fid, v in buffer.changedAttributeValues().items() if fid >= 0}
        geometrias = {fid: g for fid, g in buffer.changedGeometries().items() if fid >= 0}
        fids = sorted(set(atributos) | set(geometrias))
        bajas = sorted(fid for fid in buffer.deletedFeatureIds() if fid >= 0)
        self._pedir_versiones_que_faltan(fids + bajas)
        cambiar = []
        for fid in fids:
            version = self.version_base(fid)
            if not version:
                raise _NoSePuede(
                    f"No se sabe qué versión del elemento {fid} se editó: el servidor no la "
                    "da (¿GreenCityControl sin actualizar?). Recarga la capa y vuelve a editar."
                )
            cambio = {"id": fid, "expected_updated_at": version}
            registro = self._cache.get(fid)
            if fid in atributos:
                valores = self._atributos_para_api(atributos[fid], registro)
                if valores:
                    cambio["attributes"] = valores
            if fid in geometrias and not (
                registro is not None and registro.geometry is not None
                and _misma_geometria(registro.geometry, geometrias[fid])
            ):
                cambio["geometry"] = self._geojson(geometrias[fid], fid)
            if len(cambio) > 2:
                cambiar.append(cambio)
        retirar = []
        for fid in bajas:
            version = self.version_base(fid)
            if not version:
                raise _NoSePuede(f"No se sabe qué versión del elemento {fid} se quiere retirar.")
            retirar.append({"id": fid, "expected_updated_at": version})
        crear = [self._alta_de(fid, f) for fid, f in sorted(buffer.addedFeatures().items())]
        return {"crear": crear, "cambiar": cambiar, "retirar": retirar}

    def _alta_de(self, fid, feature):
        """Un elemento nuevo de QGIS como alta del lote. ``ref`` es su id provisional."""
        atributos = {}
        for indice, valor in enumerate(feature.attributes()):
            if indice >= self._fields.count():
                break
            if valor is None or (isinstance(valor, QVariant) and valor.isNull()):
                continue
            campo = self._fields.at(indice)
            if campo.name() == S.CAMPO_ADJUNTOS:
                atributos.update(A.para_el_alta(A.leer(valor)))
                continue
            attr = self._attr_map.get(campo.name())
            if attr is None or campo.name() in DE_GEOSIAN or S.is_computed(attr) or not S.is_editable(attr):
                # id, object_id, updated_at…, los calculados y lo de solo lectura: los pone
                # Geosian. Llegan, por ejemplo, al pegar elementos copiados de otra capa.
                continue
            nuevo = valor_para_api(valor, campo.type())
            _comprobar_numero(campo, nuevo)
            _comprobar_lista(attr, campo, nuevo, None)
            atributos[attr["name"]] = nuevo
        return {"ref": str(fid), "geometry": self._geojson(feature.geometry(), "nuevo"), "attributes": atributos}

    def _geojson(self, geometria, fid):
        """Una geometría de la capa como GeoJSON en 4326, que es como la guarda Geosian.

        Sin altura (Z) ni medida (M): Geosian guarda en 2D y rechaza una geometría con Z.
        QGIS no lo comprueba al cambiar la geometría de un elemento (sí en las altas), y
        es lo que traen los datos de GPS o de CAD. Lo mismo que hace QGIS al pegar.
        Las curvas salen ya troceadas en tramos rectos (``asJson``).
        """
        if geometria is None or geometria.isNull() or geometria.isEmpty():
            raise _NoSePuede(f"El elemento {fid} se ha quedado sin geometría; GreenCityControl no lo admite.")
        geometria = QgsGeometry(geometria)
        geometria.get().dropZValue()
        geometria.get().dropMValue()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if self._crs.isValid() and self._crs != wgs84:
            geometria.transform(QgsCoordinateTransform(self._crs, wgs84, QgsProject.instance()))
        return json.loads(geometria.asJson())

    def _pedir_versiones_que_faltan(self, fids):
        """La versión de lo que se editó sin que el proveedor lo hubiera descargado.

        Pasa con la calculadora de campos o al editar por id: QGIS no siempre lee el
        elemento antes. Lo que no se vio no se puede haber leído viejo, así que vale
        la versión de ahora.
        """
        from .provider import _features_from

        faltan = [fid for fid in fids if not self.version_base(fid)]
        if not faltan:
            return
        try:
            datos = self._client.geodata_paginated(
                self._uri.layer_id,
                page_size=len(faltan),
                data_type=self._uri.geometry_type,
                ids=faltan,
            )
        except GeosianError as exc:
            raise _NoSePuede(f"No se pudo leer la versión de los elementos editados: {exc}") from exc
        with self._lock:
            for elemento in _features_from(datos):
                self._store(elemento)

    def _atributos_para_api(self, valores, registro=None):
        """``{índice: valor}`` de QGIS como ``{nombre: valor}`` de la API.

        Con ``registro`` (lo que hay en la caché), lo que no cambia no se manda: QGIS
        apunta un cambio aunque se vuelva a poner el mismo valor, y quedarse con lo
        de Geosian ante un conflicto es justo eso.
        """
        salida = {}
        for indice, valor in valores.items():
            tipo = self._fields.at(indice).type()
            if (
                registro is not None
                and indice < len(registro.attributes)
                and valor_para_api(valor, tipo) == valor_para_api(registro.attributes[indice], tipo)
            ):
                continue
            campo = self._fields.at(indice)
            if campo.name() == S.CAMPO_ADJUNTOS:
                if A.leer(valor):
                    raise _NoSePuede(
                        "Desde QGIS solo se añaden fotos y archivos a elementos nuevos; a uno "
                        "ya guardado, desde la web."
                    )
                continue
            attr = self._attr_map.get(campo.name())
            if attr is None or campo.name() in DE_GEOSIAN:
                raise _NoSePuede(
                    f"«{campo.displayName()}» no se puede cambiar desde QGIS: lo pone GreenCityControl."
                )
            if not S.is_editable(attr):
                raise _NoSePuede(f"«{campo.displayName()}» es de solo lectura en GreenCityControl.")
            if S.is_computed(attr):
                raise _NoSePuede(
                    f"«{campo.displayName()}» es un campo calculado: lo rellena GreenCityControl al guardar."
                )
            nuevo = valor_para_api(valor, campo.type())
            viejo = _sin_nulo(registro.attributes[indice]) if registro is not None and indice < len(registro.attributes) else None
            _comprobar_numero(campo, nuevo)
            _comprobar_lista(attr, campo, nuevo, viejo)
            salida[attr["name"]] = nuevo
        return salida

    def _enviar(self, quien):
        """La primera escritura manda el lote; las siguientes ya lo dan por hecho."""
        if self._hecho is not None:
            return True
        if self._foto is None:
            # Sin foto no se escribe: mejor fallar que mandar medio lote.
            self.pushError(
                "GreenCityControl: la confirmación no pasó por el complemento. Vuelve a confirmar."
            )
            return False
        if self._foto["error"]:
            self.pushError(self._foto["error"])
            self._foto = None
            return False
        lote = self._foto["lote"]
        if not (lote["crear"] or lote["cambiar"] or lote["retirar"]):
            # Todo lo pendiente era volver a poner lo que ya había.
            self._hecho = {}
            return True
        huella = json.dumps(lote, sort_keys=True, default=str)
        donde = (self._uri.connection, self._uri.layer_id, self._uri.geometry_type)
        try:
            lote_id = self._identificador_de_lote(huella)
            pendientes.apuntar(*donde, lote_id)
        except _NoSePuede as exc:
            self.pushError(f"GreenCityControl: {exc}")
            self._foto = None
            return False
        except Exception as exc:  # una excepción aquí tumbaría QGIS
            self.pushError(f"GreenCityControl no ha guardado nada: {exc}")
            self._foto = None
            return False
        try:
            respuesta = self._client.confirmar(
                self._uri.layer_id, self._uri.geometry_type, **lote,
                esperar=_esperar_pintando, al_encolar=self.al_encolar, lote_id=lote_id,
            )
        except LoteIncierto as exc:
            # El apunte se queda: al reabrir o al volver a guardar se pregunta cómo acabó.
            self._incierto = (huella, lote_id)
            self.pushError(f"GreenCityControl: {exc}")
            self._foto = None
            return False
        except Exception as exc:  # una excepción aquí tumbaría QGIS
            # Cualquier otra respuesta es segura: el lote no entró.
            pendientes.olvidar(*donde)
            self._incierto = None
            return self._fallo_de_confirmar(exc)
        pendientes.olvidar(*donde)
        self._incierto = None
        self._hecho = respuesta or {}
        self._aplicar_respuesta(lote, self._hecho)
        return True

    def _identificador_de_lote(self, huella):
        """El ``lote_id`` con el que se manda: el mismo si se reenvía lo que no se supo.

        Si quedó un lote sin respuesta y lo que se guarda ahora es otra cosa, antes se
        pregunta a Geosian cómo acabó aquel: si entró, o aún se está aplicando, mandar
        esto podría repetir sus altas (``_NoSePuede``).
        """
        apunte = pendientes.apuntado(self._uri.connection, self._uri.layer_id, self._uri.geometry_type)
        if apunte is None:
            return str(uuid.uuid4())
        if self._incierto == (huella, apunte["lote_id"]):
            return apunte["lote_id"]
        estado = self.revisar_lote_sin_respuesta()
        if estado is None:
            raise _NoSePuede(
                "no se ha podido preguntar cómo acabó el guardado anterior de esta capa. "
                "Vuelve a intentarlo cuando haya conexión."
            )
        if estado[0] == "entro":
            raise _NoSePuede(
                f"el guardado anterior de esta capa ({estado[1]}) sí entró. Descarta estos "
                "cambios y recarga la capa para ver lo que hay antes de repetir nada."
            )
        if estado[0] == "en_curso":
            raise _NoSePuede(
                f"el guardado anterior de esta capa ({estado[1]}) aún se está aplicando. "
                "Espera a que acabe y recarga la capa."
            )
        return str(uuid.uuid4())

    def revisar_lote_sin_respuesta(self):
        """Cómo acabó el lote que quedó sin respuesta: ``(estado, hora)`` o ``None``.

        ``estado`` es ``entro``, ``en_curso`` o ``no_consta``; con los dos que cierran
        el asunto, el apunte se borra. ``None`` si no hay apunte o no se pudo preguntar.
        """
        if self._uri is None or self._client is None:
            return None
        donde = (self._uri.connection, self._uri.layer_id, self._uri.geometry_type)
        apunte = pendientes.apuntado(*donde)
        if apunte is None:
            return None
        try:
            estado = (self._client.estado_de_lote(apunte["lote_id"]) or {}).get("estado")
        except Exception:  # sin red: se volverá a preguntar
            return None
        if estado in ("entro", "no_consta"):
            pendientes.olvidar(*donde)
            self._incierto = None
        hora = time.strftime("%d/%m %H:%M", time.localtime(apunte.get("cuando") or 0))
        return estado, hora

    def _fallo_de_confirmar(self, exc):
        """El lote no entró: dice por qué y devuelve ``False`` para que QGIS lo deje pendiente."""
        self._foto = None
        if isinstance(exc, ConflictError):
            self.pushError(texto_de_conflicto(exc))
            self.conflictos = conflictos_de(exc)
            if self.al_conflicto is not None:
                self.al_conflicto(list(self.conflictos))
        elif isinstance(exc, (ForbiddenError, HttpError, NetworkError, GeosianError)):
            self.pushError(f"GreenCityControl no ha guardado nada: {texto_de_error(exc)}")
        else:
            self.pushError(f"GreenCityControl no ha guardado nada: {exc}")
        return False

    def _aplicar_respuesta(self, lote, respuesta):
        """Lo confirmado, a la caché: valores nuevos, versiones nuevas y lo retirado fuera."""
        versiones = {c["id"]: c.get("updated_at") for c in respuesta.get("cambiados", [])}
        # Lo que puso Geosian al guardar: calculados, REFER, disparadores...
        calculados = {c["id"]: c.get("calculados") or {} for c in respuesta.get("cambiados", [])}
        with self._lock:
            for baja in lote["retirar"]:
                if self._cache.pop(baja["id"], None) is not None:
                    self._feature_count = max(self._feature_count - 1, 0)
            for cambio in lote["cambiar"]:
                registro = self._cache.get(cambio["id"])
                if registro is None:
                    continue
                if "geometry" in cambio:
                    from ..core import compat

                    nueva = compat.geometry_from_geojson(cambio["geometry"])
                    if nueva is not None:
                        registro.geometry = nueva
                atributos = {**(cambio.get("attributes") or {}), **calculados.get(cambio["id"], {})}
                for nombre, valor in atributos.items():
                    indice = self._indice_de(nombre)
                    if indice >= 0:
                        registro.attributes[indice] = valor
                version = versiones.get(cambio["id"])
                if version:
                    registro.version = version
                    if self._base is not None:
                        self._base[cambio["id"]] = version

    # ------------------------------------------------------------------
    # Resolver un conflicto, elemento a elemento (decisión 3)
    # ------------------------------------------------------------------

    def sobrescribir(self, fid, version):
        """Quedarse con lo mío: la próxima confirmación se da por enterada de ``version``."""
        if self._base is not None:
            self._base[fid] = version
        registro = self._cache.get(fid)
        if registro is not None:
            registro.version = version

    def traer_de_geosian(self, fids):
        """Lo que hay ahora en Geosian de ``fids``, a la caché y como versión base.

        Devuelve los registros; los que ya no están (retirados) no vuelven.
        """
        from .provider import _features_from

        datos = self._client.geodata_paginated(
            self._uri.layer_id, page_size=max(len(fids), 1), data_type=self._uri.geometry_type, ids=list(fids)
        )
        traidos = {}
        with self._lock:
            for elemento in _features_from(datos):
                if self._store(elemento):
                    fid = int((elemento.get("properties") or {}).get("id"))
                    registro = self._cache[fid]
                    if self._base is not None:
                        self._base[fid] = registro.version
                    traidos[fid] = registro
        return traidos

    def _guardar_altas(self, flist):
        """Las altas confirmadas, con su id real, a la caché. Devuelve la lista para QGIS."""
        from .provider import CachedFeature

        creados = {c["ref"]: c for c in (self._hecho or {}).get("creados", [])}
        with self._lock:
            for feature in flist:
                creado = creados.get(str(feature.id()))
                if creado is None:
                    continue
                feature.setId(creado["id"])
                valores = list(feature.attributes())[: self._fields.count()]
                # Las fotos y los ficheros ya son del elemento en Geosian: el campo se vacía.
                for nombre, valor in (
                    ("id", creado["id"]), ("object_id", creado.get("object_id")), (S.CAMPO_ADJUNTOS, None),
                ):
                    indice = self._fields.indexOf(nombre)
                    if indice >= 0:
                        valores[indice] = valor
                        feature.setAttribute(indice, valor)
                # Lo que puso Geosian al guardar (calculados, REFER, valores por defecto,
                # disparadores). Un calculado o un campo de solo lectura pegados no se
                # mandaron: si Geosian no les puso nada, quedan vacíos.
                calculados = creado.get("calculados") or {}
                for nombre, attr in self._attr_map.items():
                    indice = self._fields.indexOf(nombre)
                    if indice < 0 or nombre in DE_GEOSIAN:
                        # id y object_id ya están puestos arriba.
                        continue
                    if attr["name"] in calculados:
                        valores[indice] = calculados[attr["name"]]
                    elif S.is_computed(attr) or not S.is_editable(attr):
                        valores[indice] = None
                    else:
                        continue
                    feature.setAttribute(indice, valores[indice])
                self._cache[creado["id"]] = CachedFeature(
                    QgsGeometry(feature.geometry()), valores, creado.get("object_id"), creado.get("updated_at")
                )
                if self._base is not None:
                    self._base[creado["id"]] = creado.get("updated_at")
                self._feature_count += 1
        return flist

    def subir_adjunto(self, campo, nombre, contenido):
        """Sube una foto o un fichero para un alta de esta capa. Devuelve la respuesta
        de Geosian, con la referencia en ``adjunto``. Lanza ``GeosianError``."""
        return self._client.subir_adjunto(
            self._uri.layer_id, self._uri.geometry_type, campo, nombre, contenido
        )

    def campos_de_adjuntos(self):
        """``[(nombre, título, tipo)]`` de los campos de fotos y ficheros del LAD, en su
        orden; ``tipo`` es ``foto`` o ``fichero``."""
        return [
            (a["name"], S.field_title(a) or a["name"], "foto" if a.get("type") == "images" else "fichero")
            for a in S.flatten_attributes(getattr(self, "_schema", None) or {})
            if S.is_attachment(a) and a.get("name")
        ]

    def puede_dar_altas(self):
        return bool((self._permisos or {}).get("can_create"))

    def _indice_de(self, nombre_api):
        for nombre, attr in self._attr_map.items():
            if attr.get("name") == nombre_api:
                return self._fields.indexOf(nombre)
        return -1

    # ------------------------------------------------------------------
    # Lo que llama QGIS
    # ------------------------------------------------------------------

    def changeAttributeValues(self, attr_map):
        return self._escritura_de_qgis("changeAttributeValues")

    def changeGeometryValues(self, geometry_map):
        return self._escritura_de_qgis("changeGeometryValues")

    def changeFeatures(self, attr_map, geometry_map):
        return self._escritura_de_qgis("changeFeatures")

    def deleteFeatures(self, ids):
        return self._escritura_de_qgis("deleteFeatures")

    def addFeatures(self, flist, flags=None):
        try:
            if not self._enviar("addFeatures"):
                return False, flist
            return True, self._guardar_altas(flist)
        except Exception as exc:  # una excepción en un método virtual tumba QGIS
            self.pushError(f"GreenCityControl: {exc}")
            return False, flist

    def _escritura_de_qgis(self, quien):
        try:
            return self._enviar(quien)
        except Exception as exc:  # una excepción en un método virtual tumba QGIS
            self.pushError(f"GreenCityControl: {exc}")
            return False


def _esperar_pintando(segundos):
    """Espera sin congelar la ventana: QGIS se pinta, pero no atiende ratón ni teclado.

    Mientras Geosian aplica un lote grande, QGIS está a mitad de confirmar la capa.
    """
    bucle = QEventLoop()
    QTimer.singleShot(int(segundos * 1000), bucle.quit)
    bucle.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)


def _comprobar_lista(attr, campo, nuevo, viejo):
    """Una lista cerrada solo admite sus valores, como el formulario de la web.

    Lo que ya estaba guardado fuera de la lista se conserva (la web también), pero no
    se puede poner de nuevo. Sin lista conocida (las que dependen de otro campo), no
    se comprueba nada: se deja en lo más permisivo, como el resto del esquema.
    """
    if attr.get("type") not in S.CHOICE_TYPES or S.is_boolean(attr) or nuevo is None:
        return
    permitidos = {str(v) for v in S.allowed_values(attr)}
    if not permitidos:
        return
    ya = {str(v) for v in (viejo if isinstance(viejo, list) else [viejo]) if v is not None}
    valores = nuevo if isinstance(nuevo, list) else [nuevo]
    fuera = [str(v) for v in valores if str(v) not in permitidos and str(v) not in ya]
    if fuera:
        raise _NoSePuede(
            f"«{campo.displayName()}»: {', '.join(f'«{v}»' for v in fuera)} no está en su lista de "
            "valores en GreenCityControl."
        )


def _comprobar_numero(campo, nuevo):
    """Un campo de número solo admite números.

    Los datos importados antes del LAD traen texto en campos de número ("0-5 m"). Eso
    se deja estar mientras no se toque; lo que se escribe nuevo tiene que ser un número.
    """
    if campo.type() not in (QVariant.LongLong, QVariant.Double) or nuevo is None:
        return
    if isinstance(nuevo, bool) or not isinstance(nuevo, (int, float)):
        raise _NoSePuede(
            f"\"{campo.displayName()}\" es un número en GreenCityControl y \"{nuevo}\" no lo es."
        )


def _misma_geometria(una, otra):
    """Coordenada a coordenada. ``equals`` está en desuso desde QGIS 4.2."""
    exacta = getattr(una, "isExactlyEqual", None)
    return bool(exacta(otra)) if exacta is not None else una.equals(otra)


def _sin_nulo(valor):
    if isinstance(valor, QVariant) and valor.isNull():
        return None
    return valor


def conflictos_de(exc):
    """Los choques del cuerpo de un 409 de ``/geodata/confirmar/``."""
    try:
        cuerpo = json.loads(exc.body or b"{}")
    except (TypeError, ValueError):
        return []
    choques = cuerpo.get("conflictos") if isinstance(cuerpo, dict) else None
    return [c for c in choques or [] if isinstance(c, dict) and "id" in c]


class _NoSePuede(Exception):
    """Lo pendiente no se puede mandar a Geosian tal cual."""


def valor_para_api(valor, tipo):
    """Un valor de QGIS como lo guarda Geosian (lo que manda la web)."""
    if valor is None or (isinstance(valor, QVariant) and valor.isNull()):
        return None
    if isinstance(valor, QDateTime):
        return valor.toString("yyyy-MM-ddTHH:mm:ss") if valor.isValid() else None
    if isinstance(valor, QDate):
        return valor.toString("yyyy-MM-dd") if valor.isValid() else None
    if isinstance(valor, QTime):
        return valor.toString("HH:mm:ss") if valor.isValid() else None
    if tipo == QVariant.StringList:
        if isinstance(valor, str):
            return [valor] if valor else None
        lista = [v for v in list(valor) if v is not None]
        return lista or None
    if tipo == QVariant.Bool:
        return bool(valor)
    if tipo in (QVariant.LongLong, QVariant.Double):
        return como_numero(valor, tipo)
    if tipo == QVariant.String and isinstance(valor, (int, float)) and not isinstance(valor, bool):
        # Un número guardado en un campo de texto: QGIS lo pasa a texto al recalcularlo,
        # y 2.0 como "2".
        return str(int(valor)) if isinstance(valor, float) and valor.is_integer() else str(valor)
    return valor if isinstance(valor, (str, int, float, bool, list)) else str(valor)


def como_numero(valor, tipo):
    """Un valor de un campo de número (``LongLong`` o ``Double``) como número.

    Los datos importados antes del LAD traen números como texto ("430"), textos que
    no son números ("0-5 m") y textos vacíos. Un texto vacío es que no hay valor; lo
    que no es un número se queda como está, sin lanzar: ``_comprobar_numero`` decide.
    """
    if valor is None or isinstance(valor, bool):
        return valor
    texto = valor.strip() if isinstance(valor, str) else valor
    if texto == "":
        return None
    if tipo == QVariant.LongLong and not isinstance(texto, float):
        # Antes que float: un entero grande perdería cifras.
        try:
            return int(texto)
        except (TypeError, ValueError):
            pass
    try:
        numero = float(texto)
    except (TypeError, ValueError):
        return valor
    if not math.isfinite(numero):
        # "nan" o "inf" no caben en el JSON que espera Geosian.
        return valor
    if tipo == QVariant.LongLong:
        return int(numero) if numero.is_integer() else valor
    return numero


def texto_de_conflicto(exc):
    """Qué elementos tocó otro, para la barra de mensajes."""
    import json

    try:
        cuerpo = json.loads(exc.body or b"{}")
    except (TypeError, ValueError):
        cuerpo = {}
    choques = cuerpo.get("conflictos") or []
    partes = []
    for choque in choques[:5]:
        quien = (choque.get("updated_by") or {}).get("nombre") or (choque.get("updated_by") or {}).get("username")
        estado = " (retirado)" if choque.get("object_status") not in (None, "disponible") else ""
        partes.append(f"{choque.get('id')}{estado}" + (f" por {quien}" if quien else ""))
    resto = f" y {len(choques) - 5} más" if len(choques) > 5 else ""
    return (
        "GreenCityControl no ha guardado nada: alguien cambió estos elementos después de que los "
        f"leyeras: {', '.join(partes)}{resto}. Tus cambios siguen pendientes."
    )


def texto_de_error(exc):
    """El motivo de un 400 o 403 de confirmar, legible."""
    import json

    try:
        cuerpo = json.loads(getattr(exc, "body", None) or b"{}")
    except (TypeError, ValueError):
        return str(exc)
    errores = cuerpo.get("errores") if isinstance(cuerpo, dict) else None
    if errores:
        textos = []
        for error in errores[:3]:
            if error.get("id") is not None:
                textos.append(f"elemento {error['id']}: {error.get('error')}")
            elif error.get("ref") is not None:
                textos.append(f"elemento nuevo: {error.get('error')}")
            else:
                textos.append(str(error.get("error")))
        return "; ".join(textos)
    if isinstance(cuerpo, dict) and cuerpo.get("error"):
        return str(cuerpo["error"])
    return str(exc)
