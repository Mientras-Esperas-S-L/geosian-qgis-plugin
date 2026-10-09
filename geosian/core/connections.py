"""Conexiones guardadas.

Una conexión es un nombre, la dirección del servidor y el correo del usuario.
El token **no** se guarda junto a lo demás: va al gestor de autenticación de
QGIS, que lo cifra. Si el usuario no tiene contraseña maestra configurada, el
token se queda solo en memoria y habrá que volver a entrar al reabrir QGIS,
que es preferible a dejarlo escrito en claro en el perfil.
"""

import time

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

from . import definitions
from .client import GeosianClient

GROUP = "geosian/connections"

# Tokens de esta sesión, para cuando el gestor de autenticación no está
# disponible. Se pierden al cerrar QGIS a propósito.
_memoria = {}
_clientes = {}


def list_connections():
    ajustes = QgsSettings()
    ajustes.beginGroup(GROUP)
    nombres = ajustes.childGroups()
    ajustes.endGroup()
    return sorted(nombres)


def get_connection(nombre):
    """Devuelve ``{url, email, authcfg}`` o ``None`` si no existe."""
    ajustes = QgsSettings()
    ajustes.beginGroup(f"{GROUP}/{nombre}")
    url = ajustes.value("url", "")
    email = ajustes.value("email", "")
    authcfg = ajustes.value("authcfg", "")
    ajustes.endGroup()
    if not url:
        return None
    return {"name": nombre, "url": url, "email": email, "authcfg": authcfg}


def ws_url(nombre):
    """URL del canal de tiempo real si la conexión la fija, o ``None``.

    Normalmente es la de la API (``wss://<api>/ws/layer-data/``). En desarrollo
    la sirve otro proceso en otro puerto, como en la web (``:8001``).
    """
    return QgsSettings().value(f"{GROUP}/{nombre}/ws_url", "") or None


def set_ws_url(nombre, url):
    QgsSettings().setValue(f"{GROUP}/{nombre}/ws_url", url or "")


def save_connection(nombre, url, email, token=None, jwt=None):
    """Guarda la conexión y, si se puede, la credencial cifrada."""
    authcfg = ""
    if token:
        authcfg = _store_token(nombre, token, jwt) or ""
        if not authcfg:
            _memoria[nombre] = {"token": token, "jwt": jwt}

    ajustes = QgsSettings()
    ajustes.beginGroup(f"{GROUP}/{nombre}")
    ajustes.setValue("url", url.rstrip("/"))
    ajustes.setValue("email", email or "")
    if authcfg:
        ajustes.setValue("authcfg", authcfg)
    ajustes.endGroup()
    _clientes.pop(nombre, None)


def remove_connection(nombre):
    conexion = get_connection(nombre)
    if conexion and conexion.get("authcfg"):
        try:
            QgsApplication.authManager().removeAuthenticationConfig(
                conexion["authcfg"]
            )
        except Exception:
            pass
    ajustes = QgsSettings()
    ajustes.beginGroup(GROUP)
    ajustes.remove(nombre)
    ajustes.endGroup()
    _memoria.pop(nombre, None)
    _clientes.pop(nombre, None)
    definitions.forget(nombre)


def get_credentials(nombre):
    """Token y JWT de una conexión, de donde estén."""
    if nombre in _memoria:
        return _memoria[nombre]

    conexion = get_connection(nombre)
    if not conexion or not conexion.get("authcfg"):
        return {}

    try:
        gestor = QgsApplication.authManager()
        config = QgsAuthMethodConfig()
        gestor.loadAuthenticationConfig(conexion["authcfg"], config, True)
        token = config.config("password", "")
        jwt = config.config("geosian_jwt", "")
        if token:
            return {"token": token, "jwt": jwt}
    except Exception:
        pass
    return {}


def _store_token(nombre, token, jwt=None):
    """Mete el token en el gestor de autenticación. Devuelve su id o ``None``."""
    try:
        gestor = QgsApplication.authManager()
        if gestor.isDisabled():
            return None

        config = QgsAuthMethodConfig()
        config.setName(f"Geosian: {nombre}")
        config.setMethod("Basic")
        config.setConfig("username", "token")
        config.setConfig("password", token)
        if jwt:
            config.setConfig("geosian_jwt", jwt)

        existente = get_connection(nombre) or {}
        if existente.get("authcfg"):
            config.setId(existente["authcfg"])
            if gestor.updateAuthenticationConfig(config):
                return existente["authcfg"]

        if gestor.storeAuthenticationConfig(config):
            return config.id()
    except Exception:
        pass
    return None


def set_session(nombre, token, jwt=None):
    """Guarda la credencial de la sesión en curso sin tocar los ajustes."""
    _memoria[nombre] = {"token": token, "jwt": jwt}
    _clientes.pop(nombre, None)


# Conexiones cuya sesión ha rechazado el servidor al abrir una capa (al reabrir un
# proyecto, normalmente). La interfaz las ofrece para volver a entrar.
_caducadas = set()


_al_caducar = []


def mark_expired(nombre):
    nueva = nombre not in _caducadas
    _caducadas.add(nombre)
    if nueva:
        # Copia: un oyente puede darse de baja mientras se recorre.
        for avisar in list(_al_caducar):  # noqa: PERF101
            avisar(nombre)


def add_expired_listener(funcion):
    _al_caducar.append(funcion)


def remove_expired_listener(funcion):
    if funcion in _al_caducar:
        _al_caducar.remove(funcion)


def expired():
    return set(_caducadas)


def clear_expired(nombre=None):
    if nombre is None:
        _caducadas.clear()
    else:
        _caducadas.discard(nombre)


# Conexiones sin red: hasta cuándo no se vuelve a intentar. Cada intento contra un
# servidor caído bloquea la interfaz hasta agotar la espera, y la tabla de
# atributos o la ficha piden datos sin parar.
_sin_red = {}
PAUSA_SIN_RED = 30


def mark_offline(nombre, segundos=PAUSA_SIN_RED):
    _sin_red[nombre] = time.monotonic() + segundos


def is_offline(nombre):
    hasta = _sin_red.get(nombre)
    if hasta is None:
        return False
    if time.monotonic() >= hasta:
        _sin_red.pop(nombre, None)
        return False
    return True


def cached_client(nombre):
    """El cliente de una conexión si ya se creó, sin crearlo.

    Crear uno lee la sesión del almacén de credenciales, y eso puede pedir la
    contraseña maestra de QGIS. Lo que no necesite hablar con el servidor, como
    repintar el panel, no debe provocarlo.
    """
    return _clientes.get(nombre)


def client_for(nombre):
    """Cliente listo para usar, reutilizado entre capas de la misma conexión.

    Devuelve ``None`` si la conexión no existe. Si existe pero no hay
    credencial, devuelve el cliente igualmente: la primera llamada fallará con
    un error de autenticación, que es lo que la interfaz sabe manejar.
    """
    if nombre in _clientes:
        return _clientes[nombre]

    conexion = get_connection(nombre)
    if not conexion:
        return None

    credenciales = get_credentials(nombre)
    cliente = GeosianClient(conexion["url"], token=credenciales.get("token"))
    cliente.jwt = credenciales.get("jwt")
    _clientes[nombre] = cliente
    return cliente
