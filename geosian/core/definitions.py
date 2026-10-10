"""Copia en disco de la definición de cada capa: campos, geometría y extensión.

Sin elementos: solo lo que la API da antes de pedir datos (el esquema, los
metadatos y la vista). Sirve para abrir un proyecto con la sesión caducada. La
capa abre vacía pero con sus campos, y QGIS no la da por «no disponible» ni
pierde su formulario al guardar. Al volver a entrar, se recarga con datos.

Se guarda en el perfil de QGIS, una carpeta por conexión, y se borra con ella.
"""

import hashlib
import json
import os
import shutil

from qgis.core import QgsApplication

# Las pruebas la cambian para no escribir en el perfil de quien las corre.
DIRECTORIO = None


def _raiz():
    return DIRECTORIO or os.path.join(QgsApplication.qgisSettingsDirPath(), "geosian", "definiciones")


def _resumen(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:32]


def _ruta(conexion, base_url, uri):
    clave = "|".join(
        str(x)
        for x in (
            base_url.rstrip("/"),
            uri.map_id,
            uri.layer_id,
            uri.geometry_type,
            uri.view_id,
            uri.info_name,
        )
    )
    return os.path.join(_raiz(), _resumen(conexion), _resumen(clave) + ".json")


def save(conexion, base_url, uri, respuestas):
    """Guarda lo que respondió la API al abrir la capa. Un fallo no importa."""
    ruta = _ruta(conexion, base_url, uri)
    try:
        os.makedirs(os.path.dirname(ruta), mode=0o700, exist_ok=True)
        temporal = ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8") as fichero:
            json.dump(respuestas, fichero)
        os.replace(temporal, ruta)
    except (OSError, TypeError, ValueError):
        pass


def load(conexion, base_url, uri):
    """Lo guardado de esa capa, o ``None`` si nunca se abrió aquí."""
    try:
        with open(_ruta(conexion, base_url, uri), encoding="utf-8") as fichero:
            datos = json.load(fichero)
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def forget(conexion):
    """Borra las definiciones de una conexión (al quitarla)."""
    shutil.rmtree(os.path.join(_raiz(), _resumen(conexion)), ignore_errors=True)
