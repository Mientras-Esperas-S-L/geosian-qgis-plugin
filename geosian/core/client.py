"""Cliente de la API de Geosian.

Envuelve los endpoints que necesita el complemento y traduce los códigos de
error a las excepciones de ``errors.py``. No depende de QGIS: el transporte se
inyecta, así que se puede usar y probar por separado.
"""

import json
from urllib.parse import urlencode

from .errors import (
    ApiError,
    AuthError,
    ConflictError,
    NotFoundError,
)
from .http import DEFAULT_TIMEOUT, default_transport

API_PREFIX = "/api/v1"


class GeosianClient:
    """Acceso a la API de Geosian.

    Args:
        base_url: raíz del servidor, por ejemplo ``https://api.greencitycontrol.com``.
        transport: transporte a usar. Por omisión, el de QGIS si está disponible.
        token: token de la API, si ya se hizo login antes.
    """

    def __init__(self, base_url, transport=None, token=None, timeout=DEFAULT_TIMEOUT):
        self.base_url = (base_url or "").rstrip("/")
        self.transport = transport or default_transport()
        self.token = token
        self.jwt = None
        self.timeout = timeout
        self.user = None

    # ------------------------------------------------------------------
    # Fontanería
    # ------------------------------------------------------------------

    def _url(self, path, params=None):
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        if params:
            limpio = {k: v for k, v in params.items() if v is not None}
            if limpio:
                url = f"{url}?{urlencode(limpio, doseq=True)}"
        return url

    def _headers(self, extra=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        headers.update(extra or {})
        return headers

    def _check(self, response, url):
        """Convierte una respuesta de error en la excepción que le toca."""
        if 200 <= response.status < 300:
            return response

        mensaje = response.text[:500]
        try:
            cuerpo = response.json()
            if isinstance(cuerpo, dict):
                mensaje = (
                    cuerpo.get("detail")
                    or cuerpo.get("error")
                    or cuerpo.get("message")
                    or mensaje
                )
        except (ValueError, UnicodeDecodeError):
            cuerpo = None

        if response.status in (401, 403):
            raise AuthError(response.status, mensaje, response.body, url)
        if response.status == 404:
            raise NotFoundError(response.status, mensaje, response.body, url)
        if response.status == 409:
            raise ConflictError(response.status, mensaje, response.body, url)
        raise ApiError(response.status, mensaje, response.body, url)

    def _get(self, path, params=None):
        url = self._url(path, params)
        resp = self.transport.request("GET", url, self._headers(), timeout=self.timeout)
        return self._check(resp, url).json()

    def _post(self, path, data=None, params=None):
        url = self._url(path, params)
        body = json.dumps(data).encode("utf-8") if data is not None else None
        resp = self.transport.request(
            "POST",
            url,
            self._headers({"Content-Type": "application/json"}),
            body,
            timeout=self.timeout,
        )
        return self._check(resp, url).json()

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------

    def login(self, email, password, device_token=None):
        """Inicia sesión.

        Devuelve el diccionario de la respuesta. Puede ser una sesión completa
        (con ``api_token``) o una petición de segundo factor (``mfa_required``),
        en cuyo caso hay que llamar a :meth:`verify_2fa` con el ``mfa_token``.

        Ojo: para usuarios sin sesiones paralelas, entrar aquí cierra la sesión
        que el usuario tuviera abierta en el navegador. Es el comportamiento
        aceptado, pero conviene avisarlo en la interfaz.
        """
        datos = {"email": email, "password": password}
        if device_token:
            datos["device_token"] = device_token
        resultado = self._post("/users/login/", datos)
        self._guardar_sesion(resultado)
        return resultado

    def verify_2fa(self, mfa_token, code, remember_device=False):
        """Segunda fase del login cuando hay doble factor."""
        resultado = self._post(
            "/users/login/verify-2fa/",
            {
                "mfa_token": mfa_token,
                "otp_code": code,
                "remember_device": remember_device,
            },
        )
        self._guardar_sesion(resultado)
        return resultado

    def _guardar_sesion(self, resultado):
        if not isinstance(resultado, dict):
            return
        if resultado.get("api_token"):
            self.token = resultado["api_token"]
        if resultado.get("jwt_token"):
            self.jwt = resultado["jwt_token"]
        if resultado.get("user"):
            self.user = resultado["user"]

    @property
    def authenticated(self):
        return bool(self.token)

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------

    def maps(self):
        """Mapas visibles para el usuario."""
        return _as_list(self._get(f"{API_PREFIX}/maps/"))

    def layers(self, map_id):
        """Capas de un mapa, cada una con su ``tile_metadata``.

        Sin esos metadatos el panel no sabe qué tipos de geometría tiene cada
        capa. El servidor los omite si trabaja solo con GeoJSON
        (``GEODATA_TILE_MODE``).
        """
        return _as_list(
            self._get(
                f"{API_PREFIX}/maps/{map_id}/layers/",
                {"include_tile_metadata": "true"},
            )
        )

    def layer_metadata(self, layer_id, map_id):
        """Metadatos de tiling de una capa: recuento, extensión y geometrías.

        Es lo que permite al proveedor responder ``wkbType()``,
        ``featureCount()`` y ``extent()`` sin descargar la capa. Salen del
        listado de capas del mapa: el detalle ``/layers/<id>/`` no los devuelve
        aunque se le pida ``include_tile_metadata``.
        """
        for capa in self.layers(map_id):
            if isinstance(capa, dict) and capa.get("id") == layer_id:
                return capa.get("tile_metadata") or {}
        return {}

    def layer_attributes(self, layer_id):
        """Definiciones de atributos (LAD) de una capa, con su esquema.

        La API ya resuelve aquí los ``allowed_values`` dinámicos, así que lo que
        llega son listas de valores listas para usar.
        """
        return _as_list(
            self._get(f"{API_PREFIX}/layer-attributes/", {"layer_id": layer_id})
        )

    def layer_views(self, layer_id):
        """Vistas guardadas de una capa."""
        return _as_list(self._get(f"{API_PREFIX}/layers/{layer_id}/views/"))

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def geodata(
        self,
        layer_id,
        data_type=None,
        ids=None,
        no_geometry=False,
        show_deleted=False,
        show_retired=False,
        extra=None,
    ):
        """Elementos de una capa, en GeoJSON.

        Args:
            layer_id: capa a leer.
            data_type: tipo de geometría (``points``, ``multi_polygons``...).
                Sin él, la API une todos los tipos de la capa.
            ids: lista de identificadores concretos, para responder a las
                peticiones de QGIS que piden elementos sueltos.
            no_geometry: pide solo atributos. La tabla de atributos de QGIS no
                necesita geometría y así se ahorra la mitad de la respuesta.
        """
        params = {
            "layer_id": layer_id,
            "data_type": data_type,
            "response_format": "geojson",
        }
        if ids:
            params["ids"] = ",".join(str(i) for i in ids)
        if no_geometry:
            params["no_geometry"] = "true"
        if show_deleted:
            params["show_deleted"] = "true"
        if show_retired:
            params["show_retired"] = "true"
        params.update(extra or {})
        return self._get(f"{API_PREFIX}/geodata/", params)

    def geodata_paginated(self, layer_id, page=1, page_size=5000, data_type=None,
                          extra=None):
        """Igual que :meth:`geodata` pero por páginas.

        La API rechaza el endpoint sin paginar por encima de 100.000 elementos,
        así que las capas grandes entran por aquí.
        """
        params = {
            "layer_id": layer_id,
            "data_type": data_type,
            "page": page,
            "page_size": page_size,
        }
        params.update(extra or {})
        return self._get(f"{API_PREFIX}/geodata/paginated/", params)

    def chart_stats(self, layer_id, attributes=None):
        """Distribución de valores de atributos, calculada en el servidor.

        Es la fuente de los valores únicos que pide QGIS para la simbología
        graduada, para no tener que recorrer la capa entera en el cliente.
        """
        params = {"layer_id": layer_id}
        if attributes:
            params["attributes"] = ",".join(attributes)
        return self._get(f"{API_PREFIX}/layers/chart_stats/", params)

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    def websocket_url(self, path="/ws/layer-data/"):
        """URL del WebSocket equivalente a la base configurada.

        El token no se mete en la cadena de consulta a propósito: acabaría en
        los registros de acceso del servidor. Va por subprotocolo, que es lo que
        el backend ya acepta (``geosian`` más ``token.<jwt>``).
        """
        base = self.base_url
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):] + path
        if base.startswith("http://"):
            return "ws://" + base[len("http://"):] + path
        return base + path

    def websocket_subprotocols(self):
        return ["geosian", f"token.{self.jwt}"] if self.jwt else ["geosian"]


def _as_list(datos):
    """Normaliza respuestas que a veces vienen paginadas y a veces en bruto."""
    if datos is None:
        return []
    if isinstance(datos, dict):
        for clave in ("results", "data", "layers", "maps"):
            if isinstance(datos.get(clave), list):
                return datos[clave]
        return []
    return datos if isinstance(datos, list) else []
