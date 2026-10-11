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

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsVectorDataProvider,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QVariant

from ..core import schema as S
from ..core.errors import (
    ConflictError,
    ForbiddenError,
    GeosianError,
    HttpError,
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
                    "da (¿Geosian sin actualizar?). Recarga la capa y vuelve a editar."
                )
            cambio = {"id": fid, "expected_updated_at": version}
            if fid in atributos:
                valores = self._atributos_para_api(atributos[fid])
                if valores:
                    cambio["attributes"] = valores
            if fid in geometrias:
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
            attr = self._attr_map.get(campo.name())
            if attr is None or campo.name() in DE_GEOSIAN:
                # id, object_id, updated_at…: los pone Geosian. Llegan, por ejemplo, al
                # pegar elementos copiados de otra capa.
                continue
            if not S.is_editable(attr):
                raise _NoSePuede(
                    f"«{campo.displayName()}» es de solo lectura en Geosian: un elemento nuevo "
                    "no puede traerlo relleno."
                )
            atributos[attr["name"]] = valor_para_api(valor, campo.type())
        return {"ref": str(fid), "geometry": self._geojson(feature.geometry(), "nuevo"), "attributes": atributos}

    def _geojson(self, geometria, fid):
        """Una geometría de la capa como GeoJSON en 4326, que es como la guarda Geosian."""
        if geometria is None or geometria.isNull() or geometria.isEmpty():
            raise _NoSePuede(f"El elemento {fid} se ha quedado sin geometría; Geosian no lo admite.")
        geometria = QgsGeometry(geometria)
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

    def _atributos_para_api(self, valores):
        """``{índice: valor}`` de QGIS como ``{nombre: valor}`` de la API."""
        salida = {}
        for indice, valor in valores.items():
            campo = self._fields.at(indice)
            attr = self._attr_map.get(campo.name())
            if attr is None or campo.name() in DE_GEOSIAN:
                raise _NoSePuede(
                    f"«{campo.displayName()}» no se puede cambiar desde QGIS: lo pone Geosian."
                )
            if not S.is_editable(attr):
                raise _NoSePuede(f"«{campo.displayName()}» es de solo lectura en Geosian.")
            salida[attr["name"]] = valor_para_api(valor, campo.type())
        return salida

    def _enviar(self, quien):
        """La primera escritura manda el lote; las siguientes ya lo dan por hecho."""
        if self._hecho is not None:
            return True
        if self._foto is None:
            # Sin foto no se escribe: mejor fallar que mandar medio lote.
            self.pushError(
                "Geosian: la confirmación no pasó por el complemento. Vuelve a confirmar."
            )
            return False
        if self._foto["error"]:
            self.pushError(self._foto["error"])
            self._foto = None
            return False
        lote = self._foto["lote"]
        try:
            respuesta = self._client.confirmar(
                self._uri.layer_id, self._uri.geometry_type, **lote
            )
        except ConflictError as exc:
            self.pushError(texto_de_conflicto(exc))
            self._foto = None
            return False
        except (ForbiddenError, HttpError, NetworkError, GeosianError) as exc:
            self.pushError(f"Geosian no ha guardado nada: {texto_de_error(exc)}")
            self._foto = None
            return False
        except Exception as exc:  # una excepción aquí tumbaría QGIS
            self.pushError(f"Geosian no ha guardado nada: {exc}")
            self._foto = None
            return False
        self._hecho = respuesta or {}
        self._aplicar_respuesta(lote, self._hecho)
        return True

    def _aplicar_respuesta(self, lote, respuesta):
        """Lo confirmado, a la caché: valores nuevos, versiones nuevas y lo retirado fuera."""
        versiones = {c["id"]: c.get("updated_at") for c in respuesta.get("cambiados", [])}
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
                for nombre, valor in (cambio.get("attributes") or {}).items():
                    indice = self._indice_de(nombre)
                    if indice >= 0:
                        registro.attributes[indice] = valor
                version = versiones.get(cambio["id"])
                if version:
                    registro.version = version
                    if self._base is not None:
                        self._base[cambio["id"]] = version

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
                for nombre, valor in (("id", creado["id"]), ("object_id", creado.get("object_id"))):
                    indice = self._fields.indexOf(nombre)
                    if indice >= 0:
                        valores[indice] = valor
                        feature.setAttribute(indice, valor)
                self._cache[creado["id"]] = CachedFeature(
                    QgsGeometry(feature.geometry()), valores, creado.get("object_id"), creado.get("updated_at")
                )
                if self._base is not None:
                    self._base[creado["id"]] = creado.get("updated_at")
                self._feature_count += 1
        return flist

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
            self.pushError(f"Geosian: {exc}")
            return False, flist

    def _escritura_de_qgis(self, quien):
        try:
            return self._enviar(quien)
        except Exception as exc:  # una excepción en un método virtual tumba QGIS
            self.pushError(f"Geosian: {exc}")
            return False


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
    if tipo == QVariant.LongLong:
        return int(valor)
    if tipo == QVariant.Double:
        return float(valor)
    return valor if isinstance(valor, (str, int, float, bool, list)) else str(valor)


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
        "Geosian no ha guardado nada: alguien cambió estos elementos después de que los "
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
            donde = error.get("id") or error.get("ref")
            textos.append(f"{donde}: {error.get('error')}" if donde is not None else str(error.get("error")))
        return "; ".join(textos)
    if isinstance(cuerpo, dict) and cuerpo.get("error"):
        return str(cuerpo["error"])
    return str(exc)
