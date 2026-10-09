"""Un servidor que responde como la API de Geosian.

Sirve para probar el proveedor de punta a punta sin depender de un Geosian de
verdad. Las respuestas imitan la forma real: GeoJSON en ``geodata``,
``tile_metadata`` en la capa y el esquema completo en ``layer-attributes``.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

ESQUEMA_ARBOLADO = {
    "name": "arbolado",
    "title": "Arbolado",
    "attributes": [
        {"name": "codigo", "type": "string", "title": "Código", "required": True},
        {"name": "object_id", "type": "string", "title": "ID", "editable": False},
        {"name": "id", "type": "integer", "title": "ID de importación"},
        {
            "name": "especie",
            "type": "select",
            "title": "Especie",
            "allowed_values": ["Platanus x hispanica", "Tilia platyphyllos"],
            "label": True,
        },
        {"name": "altura", "type": "number", "title": "Altura (m)"},
        {"name": "fecha_plantacion", "type": "calendar", "title": "Plantación"},
        {"name": "observaciones", "type": "text", "title": "Observaciones"},
        {"name": "pictures", "type": "images", "title": "Fotos"},
        {
            "name": "seccion_riesgo",
            "type": "section",
            "title": "Riesgo",
            "contents": [
                {
                    "name": "operacion",
                    "type": "checkbox",
                    "title": "Operaciones",
                    "multiple": True,
                    "allowed_values": ["Poda", "Instalación anclaje", "Tala"],
                },
                {
                    "name": "nuevo_riesgo",
                    "type": "select",
                    "title": "Nuevo nivel de riesgo",
                    "allowed_values": ["Bajo", "Medio", "Alto"],
                    "visible_if": {
                        "field": "operacion",
                        "operator": "contains_any",
                        "values": ["Instalación anclaje", "Tala"],
                    },
                },
            ],
        },
    ],
    # Como en los LAD reales: color por especie, gris para lo demás.
    "styles": {
        "colors": [
            {
                "attribute": "especie",
                "priority": 1,
                "default": "#808080",
                "allowed_values": {"Tilia platyphyllos": "#00ff00"},
            }
        ]
    },
}

MAPAS = [
    {"id": 4, "name": "Ciudad de Ejemplo: arbolado y zonas verdes", "workspace_name": "Ayuntamiento de Ejemplo"},
    # Un mapa que el usuario ve pero sobre cuyas capas no tiene permiso.
    {"id": 5, "name": "Mapa sin permiso", "workspace_name": "Otro Ayuntamiento"},
]

CAPAS = [
    {
        "id": 11,
        "name": "Arbolado",
        "map": 4,
        "tile_metadata": {
            "feature_count": 3,
            "bbox": [-3.72, 40.39, -3.68, 40.42],
            "geometry_types": ["points"],
        },
    }
]


def _punto(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


ELEMENTOS = [
    {
        "type": "Feature",
        "geometry": _punto(-3.70, 40.40),
        "properties": {
            "id": 1001,
            "object_id": "OBJ-1001",
            "updated_at": "2026-08-01T10:00:00Z",
            "codigo": "A-001",
            "especie": "Platanus x hispanica",
            "altura": 12.5,
            "fecha_plantacion": "2019-03-15",
            "observaciones": "Junto a la farola",
            "operacion": ["Poda"],
        },
    },
    {
        "type": "Feature",
        "geometry": _punto(-3.71, 40.41),
        "properties": {
            "id": 1002,
            "object_id": "OBJ-1002",
            "updated_at": "2026-08-02T11:30:00Z",
            "codigo": "A-002",
            "especie": "Tilia platyphyllos",
            "altura": 8.0,
            "operacion": ["Instalación anclaje", "Tala"],
            "nuevo_riesgo": "Alto",
        },
    },
    {
        "type": "Feature",
        # Un elemento sin geometría: la API los devuelve y no deben tumbar nada.
        "geometry": None,
        "properties": {
            "id": 1003,
            "object_id": "OBJ-1003",
            "codigo": "A-003",
            "especie": "Platanus x hispanica",
        },
    },
]


# Vista 8: iconos por especie. Es una superposición: la base sigue debajo.
VISTA_ICONOS = {
    "id": 8,
    "layer": 11,
    "name": "Iconos",
    "context_type": "elements",
    "filter_config": {"query_groups": [], "global_operator": "and"},
    "style_config": {"mode": "single", "visualization": "icon", "color": {"value": [0, 0, 255, 230]}},
}

# Vista 7 de la capa 11: solo los tilos, pintados de rojo.
VISTA_TILOS = {
    "id": 7,
    "layer": 11,
    "name": "Tilos",
    "context_type": "elements",
    "filter_config": {
        "query_groups": [
            {
                "context": "elements",
                "operator": "and",
                "rules": [
                    {"field": "especie", "operator": "in", "value": ["Tilia platyphyllos"]}
                ],
            }
        ],
        "global_operator": "and",
    },
    "style_config": {"mode": "single", "color": {"value": [255, 0, 0, 230]}},
}


def _pagina_de_elementos(consulta, lasso=None):
    """Lo que devolvería /geodata/paginated/ con esos parámetros."""
    elementos = ELEMENTOS
    ids = consulta.get("ids", [""])[0]
    if ids:
        pedidos = {int(i) for i in ids.split(",") if i}
        elementos = [e for e in elementos if e["properties"]["id"] in pedidos]
    # Los attr__ de igualdad, como el AttributeFilterMixin: varios valores, OR.
    for clave, valores in consulta.items():
        if clave.startswith("attr__") and "__" not in clave[len("attr__"):]:
            campo = clave[len("attr__"):]
            elementos = [e for e in elementos if e["properties"].get(campo) in valores]
    if lasso:
        xs = [p[0] for p in lasso["coordinates"][0]]
        ys = [p[1] for p in lasso["coordinates"][0]]
        elementos = [
            e
            for e in elementos
            if e["geometry"]
            and min(xs) <= e["geometry"]["coordinates"][0] <= max(xs)
            and min(ys) <= e["geometry"]["coordinates"][1] <= max(ys)
        ]
    pagina = int(consulta.get("page", ["1"])[0])
    return {"type": "FeatureCollection", "features": elementos if pagina == 1 else []}


class Handler(BaseHTTPRequestHandler):
    peticiones = []

    def log_message(self, *args):
        pass  # sin ruido en la salida de las pruebas

    def _json(self, datos, status=200):
        cuerpo = json.dumps(datos).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):  # noqa: N802
        partes = urlparse(self.path)
        consulta = parse_qs(partes.query)
        ruta = partes.path
        Handler.peticiones.append((ruta, consulta))

        if self.headers.get("Authorization") != "Token tok-de-prueba":
            self._json({"detail": "Credenciales no válidas"}, 401)
            return

        if ruta == "/api/v1/maps/":
            self._json(MAPAS)

        elif ruta == "/api/v1/maps/5/layers/":
            self._json({"error": "No tiene permisos para acceder a estas capas."}, 403)

        elif ruta == "/api/v1/maps/4/layers/":
            capas = [dict(c) for c in CAPAS]
            if not consulta.get("include_tile_metadata"):
                for capa in capas:
                    capa.pop("tile_metadata", None)
            self._json(capas)

        elif ruta == "/api/v1/layers/11/":
            # Como el backend: el detalle nunca trae tile_metadata.
            datos = dict(CAPAS[0])
            datos.pop("tile_metadata", None)
            self._json(datos)

        elif ruta == "/api/v1/layer-views/for-map/":
            listado = {k: VISTA_TILOS[k] for k in ("id", "layer", "name", "context_type")}
            iconos = {k: VISTA_ICONOS[k] for k in ("id", "layer", "name", "context_type")}
            self._json([{"layer_id": 11, "layer_name": "Arbolado", "views": [listado, iconos]}])

        elif ruta == "/api/v1/user-map-settings/by-map/4/":
            # El usuario tiene la capa en una carpeta, apagada y con la vista
            # de tilos activa.
            self._json(
                {
                    "settings": {
                        "layer_order": ["group:g1"],
                        "layer_groups": {
                            "g1": {"name": "Arbolado urbano", "expanded": False, "children": [11]}
                        },
                        "visible_layers": {"11": False},
                        "active_view_ids": [7],
                    },
                    "map_structure": None,
                }
            )

        elif ruta == "/api/v1/layer-views/8/":
            self._json(VISTA_ICONOS)

        elif ruta == "/api/v1/layer-views/7/":
            self._json(VISTA_TILOS)

        elif ruta == "/api/v1/layer-attributes/":
            self._json(
                [
                    {
                        "id": 2,
                        "layer": 11,
                        "geometry_type": "Point",
                        "schema": ESQUEMA_ARBOLADO,
                    }
                ]
            )

        elif ruta == "/api/v1/geodata/paginated/":
            self._json(_pagina_de_elementos(consulta))

        elif ruta == "/api/v1/geodata/":
            ids = consulta.get("ids", [""])[0]
            if ids:
                pedidos = {int(i) for i in ids.split(",") if i}
                elementos = [
                    e for e in ELEMENTOS if e["properties"]["id"] in pedidos
                ]
            else:
                elementos = ELEMENTOS
            self._json({"type": "FeatureCollection", "features": elementos})

        else:
            self._json({"detail": "No existe"}, 404)

    def do_POST(self):  # noqa: N802
        partes = urlparse(self.path)
        largo = int(self.headers.get("Content-Length") or 0)
        datos = json.loads(self.rfile.read(largo) or b"{}")

        # Como Django con APPEND_SLASH: sin la barra final no hay respuesta,
        # hay una redirección relativa que QGIS no sabe seguir.
        if not partes.path.endswith("/"):
            self.send_response(301)
            self.send_header("Location", partes.path + "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if partes.path == "/api/v1/geodata/paginated/":
            consulta = parse_qs(partes.query)
            Handler.peticiones.append((partes.path, consulta))
            if self.headers.get("Authorization") != "Token tok-de-prueba":
                self._json({"detail": "Credenciales no válidas"}, 401)
                return
            self._json(_pagina_de_elementos(consulta, datos.get("lasso_geometry")))
            return

        if partes.path == "/users/login/" and datos.get("email") == "doble@ejemplo.com":
            self._json({"mfa_required": True, "mfa_token": "mfa-de-prueba"}, 202)
            return

        if partes.path == "/users/login/verify-2fa/":
            if datos.get("mfa_token") != "mfa-de-prueba" or datos.get("otp_code") != "123456":
                self._json({"detail": "Código no válido"}, 401)
                return
            self._json(
                {
                    "api_token": "tok-de-prueba",
                    "jwt_token": "jwt-de-prueba",
                    "user": {"email": "doble@ejemplo.com"},
                },
                202,
            )
            return

        if partes.path == "/users/login/":
            self._json(
                {
                    "api_token": "tok-de-prueba",
                    "jwt_token": "jwt-de-prueba",
                    "user": {"email": "tecnico@ejemplo.com"},
                },
                202,
            )
            return
        self._json({"detail": "No existe"}, 404)


class FakeGeosian:
    """Servidor de usar y tirar, en un hilo aparte."""

    def __init__(self):
        Handler.peticiones = []
        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._hilo = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *_):
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self):
        host, puerto = self._server.server_address
        return f"http://{host}:{puerto}"

    @property
    def peticiones(self):
        return Handler.peticiones

    def rutas_pedidas(self):
        return [ruta for ruta, _ in Handler.peticiones]
