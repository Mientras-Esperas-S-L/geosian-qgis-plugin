"""Cliente de la API de Geosian.

Envuelve los endpoints que necesita el complemento y traduce los códigos de
error a las excepciones de ``errors.py``. No depende de QGIS: el transporte se
inyecta, así que se puede usar y probar por separado.
"""

import base64
import json
import time
from urllib.parse import urlencode

from .errors import (
    ApiError,
    AuthError,
    ConflictError,
    ForbiddenError,
    GeosianError,
    HttpError,
    LoteIncierto,
    NetworkError,
    NotFoundError,
)
from .http import DEFAULT_TIMEOUT, Response, default_transport

API_PREFIX = "/api/v1"
# Lo que se espera a que suba una foto o un fichero (hasta 30 MB).
PLAZO_DE_SUBIDA = 300
# Un lote grande lo aplica Geosian en segundo plano (202): se pregunta cada
# PAUSA_DE_LOTE segundos. Una vez arrancado no puede pasar de 25 minutos (el límite
# blando de Celery): ESPERA_DE_LOTE deja margen. Antes de arrancar puede esperar
# en la cola, hasta ESPERA_EN_COLA.
PAUSA_DE_LOTE = 2
ESPERA_DE_LOTE = 27 * 60
ESPERA_EN_COLA = 30 * 60
# Al cabo de esto, «no se sabe»: puede entrar todavía.
INCIERTO = (
    "No se sabe si GreenCityControl ha guardado los cambios: {motivo}. Vuelve a guardar sin "
    "tocar nada: si ya entraron, GreenCityControl lo sabe y no los repite."
)

# Cuánto se reutiliza el listado de capas de un mapa. Abrir un mapa entero son
# decenas de capas seguidas y cada una pregunta por sus metadatos: sin esto, el
# listado completo se pedía una vez por capa. Es corto a propósito para que un
# "Refrescar" del panel vea lo nuevo.
LAYERS_TTL = 30
# Lo que se espera a la definición de una capa (campos, metadatos, vista): QGIS la
# pide al abrirla, en el hilo de la ventana, que no responde mientras tanto. Son
# respuestas pequeñas; los datos van en los hilos de pintado y esperan DEFAULT_TIMEOUT.
DEFINITION_TIMEOUT = 15


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
        self._capas = {}
        self._config_teselas = {}
        self._lads = {}

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

        if response.status == 401:
            raise AuthError(response.status, mensaje, response.body, url)
        if response.status == 403:
            raise ForbiddenError(response.status, mensaje, response.body, url)
        if response.status == 404:
            raise NotFoundError(response.status, mensaje, response.body, url)
        if response.status == 409:
            raise ConflictError(response.status, mensaje, response.body, url)
        raise ApiError(response.status, mensaje, response.body, url)

    def _get(self, path, params=None, timeout=None):
        url = self._url(path, params)
        resp = self.transport.request(
            "GET", url, self._headers(), timeout=timeout or self.timeout
        )
        return self._check(resp, url).json()

    def _post(self, path, data=None, params=None, timeout=None):
        url = self._url(path, params)
        body = json.dumps(data).encode("utf-8") if data is not None else None
        resp = self.transport.request(
            "POST",
            url,
            self._headers({"Content-Type": "application/json"}),
            body,
            timeout=timeout or self.timeout,
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
        guardado = self._capas.get(map_id)
        if guardado and time.monotonic() - guardado[0] < LAYERS_TTL:
            return guardado[1]
        respuesta = self._get(
            f"{API_PREFIX}/maps/{map_id}/layers/",
            # include_permissions: lo que el usuario puede escribir en cada capa. Un
            # servidor que no lo conoce no lo manda, y la capa abre en solo lectura.
            # solo_visibles: las del mapa web también para quien gestiona permisos, que
            # sin él recibe todas (las necesita la pantalla de permisos) y abrirían vacías.
            {"include_tile_metadata": "true", "include_tile_config": "true",
             "include_permissions": "true", "solo_visibles": "true"},
            timeout=DEFINITION_TIMEOUT,
        )
        capas = _as_list(respuesta)
        # Con include_tile_config la API envuelve las capas y añade su modo de carga.
        self._config_teselas[map_id] = (
            respuesta.get("tile_config") if isinstance(respuesta, dict) else None
        )
        self._capas[map_id] = (time.monotonic(), capas)
        return capas

    def tile_config(self, map_id):
        """El ``tile_config`` del mapa (``mode``, ``auto_threshold``), o ``None``.

        Con él y los metadatos de la capa se sabe si la web la carga por teselas
        o en GeoJSON (``styles.load_mode``).
        """
        self.layers(map_id)
        return self._config_teselas.get(map_id)

    def crear_capa(self, map_id, datos):
        """Crea una capa en el mapa (``maps/<id>/layers/crear/``) y devuelve la capa.

        ``datos``: ``{"name", "plantilla", "copiar_vistas"}`` o
        ``{"name", "geometry_type", "campos"}`` (``core/crear_capa.py``).
        """
        capa = self._post(f"{API_PREFIX}/maps/{map_id}/layers/crear/", datos)
        self.forget_layers()
        return capa

    # Importar una capa grande a trozos (core/importar_grande.py,
    # maps/<id>/layers/importar/ del backend).
    def importar_capa(self, map_id, datos):
        """Abre la subida; devuelve ``id``, ``trozo``, ``trozos`` y ``faltan``."""
        return self._post(f"{API_PREFIX}/maps/{map_id}/layers/importar/", datos)

    def importar_trozo(self, map_id, id_subida, numero, datos):
        url = self._url(f"{API_PREFIX}/maps/{map_id}/layers/importar/{id_subida}/trozos/{numero}/")
        resp = self.transport.request(
            "PUT",
            url,
            self._headers({"Content-Type": "application/octet-stream"}),
            datos,
            timeout=max(self.timeout, PLAZO_DE_SUBIDA),
        )
        return self._check(resp, url).json()

    def importacion(self, map_id, id_subida):
        """Estado de la subida: ``estado``, ``faltan``, ``progreso``, ``capa_id``, ``error``."""
        return self._get(f"{API_PREFIX}/maps/{map_id}/layers/importar/{id_subida}/")

    def confirmar_importacion(self, map_id, id_subida):
        # El servidor comprueba la huella de un fichero de hasta 2 GB antes de responder: con
        # el plazo normal, la respuesta no llegaba y se confirmaba otra vez.
        estado = self._post(
            f"{API_PREFIX}/maps/{map_id}/layers/importar/{id_subida}/confirmar/",
            timeout=max(self.timeout, PLAZO_DE_SUBIDA),
        )
        self.forget_layers()
        return estado

    def cancelar_importacion(self, map_id, id_subida):
        url = self._url(f"{API_PREFIX}/maps/{map_id}/layers/importar/{id_subida}/")
        resp = self.transport.request("DELETE", url, self._headers(), timeout=self.timeout)
        return self._check(resp, url).json()

    def forget_layers(self):
        """Olvida los listados de capas guardados (el panel al refrescar)."""
        self._capas.clear()
        self._config_teselas.clear()
        self._lads.clear()

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
        # Ni está en el mapa ni el usuario la ve en él. La API no da 404 por la
        # capa en /layer-attributes/ (devuelve una lista vacía), así que este es
        # el sitio donde se sabe que ya no existe.
        raise NotFoundError(404, f"La capa {layer_id} no está en el mapa {map_id}", b"", "")

    def layer_permissions(self, layer_id, map_id):
        """Lo que el usuario puede escribir en la capa, o ``None`` si el servidor no lo dice.

        ``{"can_create", "can_update", "can_retire", "update_restringido"}``. Sale
        del listado de capas del mapa, como los metadatos.
        """
        for capa in self.layers(map_id):
            if isinstance(capa, dict) and capa.get("id") == layer_id:
                permisos = capa.get("permissions")
                return permisos if isinstance(permisos, dict) else None
        return None

    def confirmar(
        self, layer_id, geometry_type, crear=(), cambiar=(), retirar=(),
        esperar=time.sleep, al_encolar=None, lote_id=None,
    ):
        """Manda lo confirmado de una capa en un lote: entra todo o nada.

        ``POST /geodata/confirmar/``. Un 409 (:class:`ConflictError`) trae en su
        cuerpo ``conflictos``: los elementos que alguien tocó después de leerlos.

        Un lote grande Geosian lo aplica en segundo plano (202): se llama a
        ``al_encolar(total)``, se pregunta por la tarea con ``esperar(segundos)``
        entre vuelta y vuelta, y se devuelve o se lanza lo mismo que sin esperar.

        Con ``lote_id``, reenviar el mismo lote no lo aplica dos veces: si ya entró,
        Geosian responde lo de entonces.
        """
        url = self._url(f"{API_PREFIX}/geodata/confirmar/")
        cuerpo = {
            "layer_id": layer_id,
            "geometry_type": geometry_type,
            "crear": list(crear),
            "cambiar": list(cambiar),
            "retirar": list(retirar),
        }
        if lote_id:
            cuerpo["lote_id"] = lote_id
        try:
            resp = self.transport.request(
                "POST",
                url,
                self._headers({"Content-Type": "application/json"}),
                json.dumps(cuerpo).encode("utf-8"),
                # Un lote grande pesa varios megas: el plazo es el de una subida.
                timeout=max(self.timeout, PLAZO_DE_SUBIDA),
            )
        except NetworkError as exc:
            # El lote salió y pudo entrar aunque la respuesta no llegue.
            raise LoteIncierto(INCIERTO.format(motivo=f"se cortó la conexión ({exc})")) from exc
        resp = self._check(resp, url)
        if resp.status != 202:
            return resp.json()
        encolado = resp.json() or {}
        if al_encolar is not None:
            al_encolar(encolado.get("total"))
        return self._esperar_lote(encolado["task_id"], esperar)

    def estado_de_lote(self, lote_id):
        """Cómo acabó un lote propio: ``{"estado": "entro"|"en_curso"|"no_consta", ...}``.

        ``GET /geodata/confirmar/<lote_id>/``.
        """
        return self._get(f"{API_PREFIX}/geodata/confirmar/{lote_id}/") or {}

    def _esperar_lote(self, task_id, esperar):
        """Pregunta por el lote en segundo plano hasta que acaba y da su respuesta."""
        ruta = f"{API_PREFIX}/tasks/{task_id}/status/"
        inicio, arrancada = time.monotonic(), None
        while True:
            esperar(PAUSA_DE_LOTE)
            try:
                tarea = self._get(ruta)
            except NetworkError:
                # Un corte al preguntar no dice nada del lote: se sigue preguntando.
                tarea = None
            except HttpError as exc:
                if exc.status < 500:
                    # Sin credencial o sin la tarea no hay forma de saber cómo acabó.
                    raise LoteIncierto(INCIERTO.format(motivo=str(exc))) from exc
                # Un 502 o 503 al preguntar (un despliegue, un reinicio) es pasajero.
                tarea = None
            estado = (tarea or {}).get("status")
            if estado in ("SUCCESS", "FAILURE", "REVOKED"):
                break
            if estado in ("STARTED", "PROGRESS") and arrancada is None:
                arrancada = time.monotonic()
            limite = arrancada + ESPERA_DE_LOTE if arrancada else inicio + ESPERA_EN_COLA
            if time.monotonic() > limite:
                raise LoteIncierto(INCIERTO.format(motivo="no ha terminado a tiempo"))
        resultado = tarea.get("result_data") or {}
        cuerpo = resultado.get("cuerpo") or {
            "error": tarea.get("error_message") or "GreenCityControl no ha aplicado el lote."
        }
        # Lo mismo que habría respondido el lote sin esperar: mismos errores.
        self._check(
            Response(resultado.get("estado") or 500, json.dumps(cuerpo).encode("utf-8")),
            self._url(ruta),
        )
        return cuerpo

    def subir_adjunto(self, layer_id, geometry_type, campo, nombre, contenido):
        """Sube una foto o un fichero de un elemento nuevo y devuelve su referencia.

        ``POST /geodata/adjuntos/``. El alta la lleva luego en su campo como
        ``{"adjunto": ref}`` (``core/adjuntos.py``). Puede tardar: el plazo es el
        de una descarga grande, no el de una consulta.
        """
        url = self._url(f"{API_PREFIX}/geodata/adjuntos/")
        cuerpo = {
            "layer_id": layer_id,
            "geometry_type": geometry_type,
            "campo": campo,
            "nombre": nombre,
            "datos": base64.b64encode(contenido).decode("ascii"),
        }
        resp = self.transport.request(
            "POST",
            url,
            self._headers({"Content-Type": "application/json"}),
            json.dumps(cuerpo).encode("utf-8"),
            timeout=max(self.timeout, PLAZO_DE_SUBIDA),
        )
        return self._check(resp, url).json()

    def layer_attributes(self, layer_id):
        """Definiciones de atributos (LAD) de una capa, con su esquema.

        La API ya resuelve aquí los ``allowed_values`` dinámicos, así que lo que
        llega son listas de valores listas para usar.
        """
        guardado = self._lads.get(layer_id)
        if guardado and time.monotonic() - guardado[0] < LAYERS_TTL:
            return guardado[1]
        definiciones = _as_list(
            self._get(
                f"{API_PREFIX}/layer-attributes/",
                {"layer_id": layer_id},
                timeout=DEFINITION_TIMEOUT,
            )
        )
        self._lads[layer_id] = (time.monotonic(), definiciones)
        return definiciones

    def forget_layer_attributes(self, layer_id):
        """Olvida el esquema guardado de una capa: ha cambiado en GCC."""
        self._lads.pop(layer_id, None)

    def prefetch_layer_attributes(self, layer_ids):
        """Pide a la vez los LAD de varias capas y los deja guardados.

        La API los da capa a capa, porque comprueba los permisos de cada una.
        Al abrir un mapa entero de cincuenta capas, pedirlos de uno en uno era
        la mayor parte de la espera. Lo que falle se vuelve a pedir después,
        suelto, al abrir la capa.
        """
        ahora = time.monotonic()
        faltan = [
            i for i in layer_ids
            if not (i in self._lads and ahora - self._lads[i][0] < LAYERS_TTL)
        ]
        if not faltan:
            return
        urls = [self._url(f"{API_PREFIX}/layer-attributes/", {"layer_id": i}) for i in faltan]
        respuestas = self.transport.get_many(urls, self._headers(), timeout=self.timeout)
        for capa, url, respuesta in zip(faltan, urls, respuestas):
            if not isinstance(respuesta, Response):
                continue
            try:
                datos = self._check(respuesta, url).json()
            except (GeosianError, ValueError):
                continue
            self._lads[capa] = (time.monotonic(), _as_list(datos))

    def layer_views(self, layer_id):
        """Vistas guardadas de una capa."""
        return _as_list(self._get(f"{API_PREFIX}/layers/{layer_id}/views/"))

    def map_detail(self, map_id):
        """El detalle de un mapa: centro, zoom y sus fondos propios (``basemaps``)."""
        return self._get(f"{API_PREFIX}/maps/{int(map_id)}/") or {}

    def map_settings(self, map_id):
        """Preferencias del usuario en un mapa: orden, carpetas, vistas activas.

        Es la respuesta de ``user-map-settings/by-map``, con la estructura
        publicada en ``map_structure`` si la hay.
        """
        return self._get(f"{API_PREFIX}/user-map-settings/by-map/{map_id}/") or {}

    def map_views(self, map_id):
        """Vistas de las capas de un mapa: ``{layer_id: [vista, ...]}``.

        El listado no trae el filtro ni el estilo de cada vista; para eso está
        :meth:`layer_view`.
        """
        salida = {}
        for bloque in _as_list(
            self._get(f"{API_PREFIX}/layer-views/for-map/", {"map_id": map_id})
        ):
            if isinstance(bloque, dict) and bloque.get("layer_id") is not None:
                salida[bloque["layer_id"]] = bloque.get("views") or []
        return salida

    def layer_view(self, view_id):
        """Una vista completa, con ``filter_config`` y ``style_config``."""
        return self._get(f"{API_PREFIX}/layer-views/{view_id}/", timeout=DEFINITION_TIMEOUT) or {}

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
                          extra=None, area=None, ids=None):
        """Igual que :meth:`geodata` pero por páginas.

        La API rechaza el endpoint sin paginar por encima de 100.000 elementos,
        así que las capas grandes entran por aquí.

        Args:
            area: ``(oeste, sur, este, norte)`` en grados. Solo vuelve lo que
                cae dentro. Va como ``lasso_geometry`` en un POST, que es como
                lo acepta la API.
            ids: identificadores concretos.
            extra: más parámetros, por ejemplo los ``attr__`` de una vista.
        """
        params = {
            "layer_id": layer_id,
            "data_type": data_type,
            "page": page,
            "page_size": page_size,
            # La versión exacta de cada elemento (updated_at_iso), para el bloqueo
            # optimista al editar. Un servidor que no lo conoce no la manda.
            "include_version": "true",
        }
        if ids:
            params["ids"] = ",".join(str(i) for i in ids)
        params.update(extra or {})
        ruta = f"{API_PREFIX}/geodata/paginated/"
        if area:
            oeste, sur, este, norte = area
            anillo = [[oeste, sur], [este, sur], [este, norte], [oeste, norte], [oeste, sur]]
            return self._post(
                ruta,
                {"lasso_geometry": {"type": "Polygon", "coordinates": [anillo]}},
                params,
            )
        return self._get(ruta, params)

    def element_detail(self, element_id, data_type):
        """Un elemento con sus fotos (en base64) y sus ficheros (``id`` y nombre).

        Args:
            data_type: el tipo de la URI (``points``, ``polygons``…).
        """
        # Con enlaces y no con las fotos en base64: varios megas por ficha que
        # quizá nadie mire. Un servidor que no conozca el parámetro las manda
        # enteras y también vale.
        return self._get(
            f"{API_PREFIX}/geodata/{int(element_id)}/",
            {"geometry_type": data_type, "embed_images": "false"},
        )

    def tiles(self, urls):
        """Los bytes de varias teselas de la API, en paralelo y con el token."""
        respuestas = self.transport.get_many(urls, self._headers({"Accept": "*/*"}), timeout=self.timeout)
        cuerpos = []
        for respuesta, url in zip(respuestas, urls):
            if isinstance(respuesta, Exception):
                cuerpos.append(None)  # una tesela que no llega no tumba las demás
                continue
            cuerpos.append(self._check(respuesta, url).body)
        return cuerpos

    def download(self, path):
        """Bytes de una foto o un fichero servidos por la API, con el token."""
        url = self._url(path)
        resp = self.transport.request("GET", url, self._headers({"Accept": "*/*"}), timeout=self.timeout)
        return self._check(resp, url).body

    def additional_information(self, layer_id, name, geometry_type, geodata_id=None,
                               page=1, page_size=1000):
        """Una página de partes (información adicional) de un tipo.

        Con ``geodata_id``, los de ese elemento; sin él, los de toda la capa. La
        API devuelve solo los tipos que los grupos del usuario pueden ver.

        Args:
            geometry_type: como en el esquema (``Point``, ``Polygon``…); sin él
                la API no sabe en qué tabla buscar.
        """
        params = {
            "layer_id": layer_id,
            "name": name,
            "geometry_type": geometry_type,
            "page": page,
            "page_size": page_size,
        }
        if geodata_id is not None:
            # El orden del servidor, el más reciente primero: el de la web.
            params["geodata_id"] = geodata_id
        else:
            # La capa entera va por páginas: hace falta un orden estable.
            params.update({"sort_by": "id", "sort_order": "asc"})
        return self._get(f"{API_PREFIX}/additional-information/", params)

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
