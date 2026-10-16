"""Los lotes enviados que aún no tienen respuesta, apuntados en disco.

Antes de mandar un lote se apunta su ``lote_id`` en los ajustes de QGIS, y se borra
cuando llega la respuesta. Si QGIS se cierra o se corta la red mientras espera, el
apunte queda: al volver a abrir la capa, o antes del siguiente guardado, se pregunta a
Geosian cómo acabó (``GET /geodata/confirmar/<lote_id>/``). Así nadie vuelve a dibujar
unas altas que ya habían entrado sin saberlo.
"""

import json
import time

from qgis.core import QgsSettings

GRUPO = "geosian/lotes_sin_respuesta"


def _clave(conexion, layer_id, tabla):
    # Un nombre de conexión con «/» abriría subgrupos en los ajustes.
    seguro = str(conexion).replace("/", "_").replace("\\", "_")
    return f"{GRUPO}/{seguro}__{layer_id}__{tabla}"


def apuntar(conexion, layer_id, tabla, lote_id):
    ajustes = QgsSettings()
    ajustes.setValue(_clave(conexion, layer_id, tabla), json.dumps({"lote_id": lote_id, "cuando": time.time()}))
    # A disco ya: si QGIS se cae esperando, el apunte tiene que estar.
    ajustes.sync()


def apuntado(conexion, layer_id, tabla):
    """``{"lote_id", "cuando"}`` del lote sin respuesta de esa capa, o ``None``."""
    valor = QgsSettings().value(_clave(conexion, layer_id, tabla), "")
    try:
        datos = json.loads(valor) if valor else None
    except (TypeError, ValueError):
        return None
    return datos if isinstance(datos, dict) and datos.get("lote_id") else None


def olvidar(conexion, layer_id, tabla):
    ajustes = QgsSettings()
    ajustes.remove(_clave(conexion, layer_id, tabla))
    ajustes.sync()
