"""Las subidas de capas grandes abiertas desde este equipo.

Si QGIS se cierra (o se cuelga) en mitad de una, el servidor la sigue contando como «en
marcha» hasta 30 minutos sin actividad y no deja empezar otra. Por eso cada subida se apunta
en los ajustes de QGIS con el proceso que la abrió, y al abrir la siguiente se cancelan las
de un proceso que ya no existe en este equipo. Las de un QGIS que sigue abierto, o las de
otro equipo con el mismo perfil, no se tocan: dos QGIS a la vez no se pisan.
"""

import json
import os
import socket

from qgis.core import QgsSettings

CLAVE = "geosian/subidas_abiertas"


def _todas():
    try:
        lista = json.loads(QgsSettings().value(CLAVE, "") or "[]")
    except (TypeError, ValueError):
        return []
    return [e for e in lista if isinstance(e, dict) and {"servidor", "map_id", "id", "pid", "equipo"} <= e.keys()]


def _guardar(lista):
    QgsSettings().setValue(CLAVE, json.dumps(lista))


def apuntar(servidor, map_id, id_subida):
    _guardar(_todas() + [{
        "servidor": servidor, "map_id": map_id, "id": id_subida, "pid": os.getpid(), "equipo": socket.gethostname(),
    }])


def quitar(id_subida):
    _guardar([e for e in _todas() if e["id"] != id_subida])


def huerfanas(servidor):
    """Las de ``servidor`` que abrió en este equipo un QGIS que ya no está."""
    equipo = socket.gethostname()
    return [e for e in _todas() if e["servidor"] == servidor and e["equipo"] == equipo and not vivo(e["pid"])]


def vivo(pid):
    """Si el proceso ``pid`` existe. Ante la duda, sí: no cancelar lo que puede estar subiendo."""
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # En Windows, os.kill(pid, 0) no pregunta: termina el proceso.
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        proceso = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not proceso:
            # 87 (parámetro no válido): no hay tal proceso. Otro (sin permiso): existe.
            return ctypes.get_last_error() != 87
        try:
            codigo = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(proceso, ctypes.byref(codigo)):
                return True
            return codigo.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(proceso)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError, ValueError):
        return True
    return True
