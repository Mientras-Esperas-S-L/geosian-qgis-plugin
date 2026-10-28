"""Un servidor que responde como la API de Geosian.

Sirve para probar el proveedor de punta a punta sin depender de un Geosian de
verdad. Las respuestas imitan la forma real: GeoJSON en ``geodata``,
``tile_metadata`` en la capa y el esquema completo en ``layer-attributes``.
"""

import base64
import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

ESQUEMA_ARBOLADO = {
    "name": "arbolado",
    "title": "Arbolado",
    "main_attributes": ["object_id", "especie", "codigo_migracion"],
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
        {"name": "codigo_migracion", "type": "string", "title": "Código de migración",
         "visible": False},
        {"name": "pictures", "type": "images", "title": "Fotos"},
        {"name": "files", "type": "files", "title": "Archivos"},
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
    # Los partes: tipos de información adicional, con su propio esquema.
    "additional_information": [
        {
            "name": "parte_poda",
            "title": "Parte de poda",
            # Como los partes de palmeras: solo para los elementos de una especie.
            "attribute_dependencies": [{"name": "especie", "value": "Platanus x hispanica"}],
            "attributes": [
                {"name": "labor", "type": "select", "title": "Labor",
                 "allowed_values": ["Poda", "Aclareo"]},
                {"name": "horas", "type": "number", "title": "Horas"},
                {"name": "pictures", "type": "images", "title": "Fotos"},
            ],
        }
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


# Partes de poda, con la forma de /additional-information/: los atributos
# anidados, el autor como texto y el elemento en «geodata».
PARTES = [
    {"id": 501, "name": "parte_poda", "geodata": 1001, "user": "Técnica Uno",
     "created_at": "2026-05-02T09:00:00+02:00", "updated_at": "2026-05-02T09:00:00+02:00",
     "attributes": {"labor": "Poda", "horas": 2.5, "pictures": None},
     "pictures": [{"id": 88, "url": "/api/v1/additional-information/image/88/", "main_image": True}],
     "files": []},
    {"id": 502, "name": "parte_poda", "geodata": 1001, "user": "Técnico Dos",
     "created_at": "2026-06-10T12:00:00+02:00", "updated_at": "2026-06-11T08:00:00+02:00",
     "attributes": {"labor": "Aclareo", "horas": 1.0}},
    {"id": 503, "name": "parte_poda", "geodata": 1002, "user": "Técnica Uno",
     "created_at": "2026-07-01T10:00:00+02:00", "updated_at": "2026-07-01T10:00:00+02:00",
     "attributes": {"labor": "Poda", "horas": 4.0}},
]


# Una foto de verdad (PNG de 1×1) para que Qt la pueda leer.
FOTO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
FICHERO_PDF = b"%PDF-1.4 informe de prueba"
# Otra imagen de 1×1, para distinguir la miniatura de la foto entera.
MINIATURA_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# El detalle de /geodata/<id>/: fotos en base64 y ficheros con id y nombre.
DETALLES = {
    1001: {
        "pictures": [
            {"id": 71, "data": "data:image/png;base64," + base64.b64encode(FOTO_PNG).decode(),
             "created_at": "2026-05-02T09:00:00+02:00", "main_image": False, "field_name": "pictures"},
            {"id": 72, "data": "data:image/png;base64," + base64.b64encode(FOTO_PNG).decode(),
             "created_at": "2026-05-03T09:00:00+02:00", "main_image": True, "field_name": "pictures"},
        ],
        "files": [{"id": 31, "name": "informe.pdf", "field_name": "files"}],
    },
}


def _pagina_de_partes(consulta):
    """Lo que devolvería /additional-information/ con esos parámetros."""
    partes = [p for p in PARTES if p["name"] == consulta.get("name", [""])[0]]
    if consulta.get("geodata_id"):
        partes = [p for p in partes if p["geodata"] == int(consulta["geodata_id"][0])]
    tam = int(consulta.get("page_size", ["10"])[0])
    pagina = int(consulta.get("page", ["1"])[0])
    trozo = partes[(pagina - 1) * tam: pagina * tam]
    return {
        "results": trozo,
        "pagination": {"total_items": len(partes), "current_page": pagina,
                       "page_size": tam, "has_more": pagina * tam < len(partes)},
    }


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
VISTA_HEXAGONOS = {
    "id": 9,
    "layer": 11,
    "name": "Densidad",
    "context_type": "elements",
    "filter_config": {"query_groups": [{"operator": "and", "context": "elements", "rules": [
        {"field": "especie", "operator": "equals", "value": "Tilia platyphyllos"}]}]},
    "style_config": {"mode": "single", "visualization": "hexagon",
                     "hexagon": {"radius": 200, "colorRamp": "viridis", "colorMax": 50},
                     "point": {"opacity": 0.7}},
}

VISTA_CALOR = {
    "id": 10,
    "layer": 11,
    "name": "Calor",
    "context_type": "elements",
    "filter_config": {"query_groups": []},
    "style_config": {"mode": "single", "visualization": "heatmap",
                     "heatmap": {"radiusPixels": 30, "intensity": 1, "threshold": 0.05,
                                 "colorRamp": "inferno"}},
}

VISTA_CONTORNOS = {
    "id": 11,
    "layer": 11,
    "name": "Contornos",
    "context_type": "elements",
    "filter_config": {"query_groups": []},
    "style_config": {"mode": "single", "visualization": "contour", "point": {"opacity": 0.8},
                     "contour": {"cellSize": 400, "aggregation": "SUM", "contours": [
                         {"threshold": 1, "color": [255, 255, 178, 128], "strokeWidth": 1},
                         {"threshold": 5, "color": [240, 59, 32, 200], "strokeWidth": 3}]}},
}

VISTA_POR_PARTES = {
    "id": 12,
    "layer": 11,
    "name": "Por labor",
    "context_type": "elements",
    "filter_config": {"query_groups": []},
    "style_config": {"visualization": "default", "color": {
        "mode": "categorized", "attribute": "additional_info.parte_poda.labor",
        "attributeSource": "additional_info",
        "categories": {"Poda": {"color": [255, 0, 0, 230], "label": "Poda"},
                       "Aclareo": {"color": [0, 0, 255, 230], "label": "Aclareo"}},
        "default": {"color": [158, 158, 158, 230], "label": "Otros"}}},
}

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


def _pagina_de_elementos(consulta, lasso=None, servidor=None):
    """Lo que devolvería /geodata/paginated/ con esos parámetros."""
    elementos = servidor.elementos if servidor is not None else ELEMENTOS
    capa = consulta.get("layer_id", [""])[0]
    if servidor is not None and capa.isdigit() and int(capa) in servidor.elementos_de_capa:
        # Una capa creada en la prueba: sus elementos, no los del arbolado.
        elementos = servidor.elementos_de_capa[int(capa)]
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
    # include_ai_attr=<tipo>.<campo>: el valor del último parte de cada elemento, en
    # properties.additional_info.<tipo>.<campo>, como el backend.
    pedido = consulta.get("include_ai_attr", [""])[0]
    if pedido == "parte_poda.labor":
        # El 1003, como lista: en los datos reales hay selecciones con un valor de los dos modos.
        valores = {1001: "Poda", 1002: "Aclareo", 1003: ["Poda"]}
        elementos = [
            {**e, "properties": {**e["properties"], "additional_info": {
                "parte_poda": {"labor": valores[e["properties"]["id"]]}}}}
            if e["properties"]["id"] in valores else e
            for e in elementos
        ]
    if consulta.get("no_geometry") == ["true"]:
        # Como la API desde el PR de no_geometry en /paginated/: los atributos, sin forma.
        elementos = [{**e, "geometry": None} for e in elementos]
    if servidor is not None and consulta.get("include_version") == ["true"]:
        # Como la API con include_version: la versión exacta, aparte de updated_at.
        elementos = [
            {**e, "properties": {**e["properties"],
                                 "updated_at_iso": servidor.versiones.get(e["properties"]["id"])}}
            for e in elementos
        ]
    pagina = int(consulta.get("page", ["1"])[0])
    return {"type": "FeatureCollection", "features": elementos if pagina == 1 else []}


class Handler(BaseHTTPRequestHandler):
    peticiones = []  # noqa: RUF012 (la comparten el servidor y las pruebas)

    def log_message(self, *args):
        pass  # sin ruido en la salida de las pruebas

    def _json(self, datos, status=200):
        cuerpo = json.dumps(datos).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _bytes(self, cuerpo, tipo):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        partes = urlparse(self.path)
        consulta = parse_qs(partes.query)
        ruta = partes.path
        Handler.peticiones.append((ruta, consulta))

        if self.headers.get("Authorization") != "Token tok-de-prueba":
            self._json({"detail": "Credenciales no válidas"}, 401)
            return

        if re.match(r"^/api/v1/maps/\d+/layers/importar/$", ruta):
            # Como GET …/importar/: las del usuario que ocupan su cupo.
            activas = [
                _importacion(self.server, id_subida)[1] for id_subida, imp in self.server.importaciones.items()
                if imp["estado"] in ("subiendo", "importando")
            ]
            self._json({"activas": activas})
            return

        importacion = re.match(r"^/api/v1/maps/\d+/layers/importar/([^/]+)/$", ruta)
        if importacion:
            estado, cuerpo = _importacion(self.server, importacion.group(1), avanzar=True)
            self._json(cuerpo, estado)
            return

        if ruta.startswith("/api/v1/geodata/confirmar/") and ruta != "/api/v1/geodata/confirmar/":
            # Como GET /geodata/confirmar/<lote_id>/: cómo acabó un lote.
            visto = self.server.lotes_vistos.get(ruta.rstrip("/").rsplit("/", 1)[1])
            if isinstance(visto, dict):
                self._json({"estado": "entro", "respuesta": visto})
            elif isinstance(visto, str) and self.server.tareas[visto][2] is None:
                self._json({"estado": "en_curso", "task_id": visto})
            else:
                self._json({"estado": "no_consta"})
            return

        if ruta.startswith("/api/v1/tasks/") and ruta.endswith("/status/"):
            # Como el estado de una tarea de Celery: en curso unas vueltas y luego el
            # lote se aplica de una vez, con la respuesta del síncrono en result_data.
            tarea = self.server.tareas.get(ruta[len("/api/v1/tasks/"):-len("/status/")])
            if tarea is None:
                self._json({"error": "Tarea no encontrada"}, 404)
                return
            if tarea[1] > 0:
                tarea[1] -= 1
                self._json({"status": "STARTED", "result_data": None, "error_message": ""})
                return
            if tarea[2] is None:
                tarea[2] = self.server.confirmar(tarea[0])
                if tarea[0].get("lote_id") and tarea[2][0] == 200:
                    self.server.lotes_vistos[tarea[0]["lote_id"]] = tarea[2][1]
            estado, cuerpo = tarea[2]
            self._json({
                "status": "SUCCESS" if estado == 200 else "FAILURE",
                "result_data": {"estado": estado, "cuerpo": cuerpo},
                "error_message": "",
            })
            return

        if ruta.startswith("/api/v1/geodata/tiles/") and ruta.endswith(".mvt"):
            # Celdas agregadas con su centroide, como el servidor con agg=hex&geom=centroid:
            # una por elemento (y diez en la del primero, para que haya un grupo).
            from geosian.core import aggregated
            from tests.test_mvt import _tesela, _tesela_con_poligonos

            z, x, y = (int(v) for v in ruta[len("/api/v1/geodata/tiles/"):-len(".mvt")].split("/"))
            celdas, hexagonos = [], []
            for e in ELEMENTOS:
                if not e.get("geometry"):
                    continue
                lon, lat = e["geometry"]["coordinates"]
                n = 10 if e["properties"]["id"] == 1001 else 1
                celdas.append({"count": n, "lng": float(lon), "lat": float(lat)})
                # Sin geom=centroid, el hexágono entero, solo en la tesela de su centro y sin
                # recortar (puede salirse de [0, 4096]), como el servidor.
                if aggregated._tesela(lon, lat, z) == (x, y):
                    oeste, sur, este, norte = aggregated.tile_bounds(z, x, y)
                    mx, my = aggregated.to_mercator(lon, lat)
                    px = round((mx - oeste) / (este - oeste) * 4096)
                    py = round((norte - my) / (norte - sur) * 4096)
                    r = 3000
                    anillo = [(px - r, py), (px - r // 2, py - r), (px + r // 2, py - r),
                              (px + r, py), (px + r // 2, py + r), (px - r // 2, py + r)]
                    hexagonos.append(({"count": n}, [anillo]))
            if consulta.get("geom") == ["centroid"]:
                cuerpo = _tesela("agg", celdas)
            else:
                cuerpo = _tesela_con_poligonos("agg", hexagonos)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.mapbox-vector-tile")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return

        if ruta == "/api/v1/maps/":
            self._json(MAPAS)

        elif ruta == "/api/v1/maps/4/":
            # El detalle: lo que importa aquí son los fondos propios del mapa.
            self._json({
                **MAPAS[0],
                "basemaps": [{"code": "ORTO", "name": "Ortofoto de ejemplo", "kind": "xyz",
                              "min_zoom": 0, "max_zoom": 19,
                              "tiles": ["https://teselas.ejemplo.org/orto/{z}/{x}/{y}.jpg"]}],
            })

        elif ruta == "/api/v1/maps/5/layers/":
            self._json({"error": "No tiene permisos para acceder a estas capas."}, 403)

        elif ruta == "/api/v1/maps/4/layers/":
            capas = [dict(c) for c in CAPAS + self.server.capas_extra]
            if consulta.get("include_permissions") == ["true"]:
                # Como la API con include_permissions; sin entrada, ningún permiso.
                for capa in capas:
                    capa["permissions"] = dict(self.server.permisos.get(capa["id"], SIN_PERMISOS))
            if not consulta.get("include_tile_metadata"):
                for capa in capas:
                    capa.pop("tile_metadata", None)
            if consulta.get("include_tile_config") == ["true"] and self.server.tile_config:
                # Como la API: con tile_config, las capas van envueltas.
                self._json({"layers": capas, "tile_config": self.server.tile_config})
            else:
                self._json(capas)

        elif ruta == "/api/v1/layers/11/":
            # Como el backend: el detalle nunca trae tile_metadata.
            datos = dict(CAPAS[0])
            datos.pop("tile_metadata", None)
            self._json(datos)

        elif ruta == "/api/v1/layer-views/for-map/":
            listado = {k: VISTA_TILOS[k] for k in ("id", "layer", "name", "context_type")}
            iconos = {k: VISTA_ICONOS[k] for k in ("id", "layer", "name", "context_type")}
            # Una vista marcada como de información adicional: la web la pinta igual.
            partes = {"id": 9, "layer": 11, "name": "Con partes", "context_type": "additional_info"}
            self._json(
                [{"layer_id": 11, "layer_name": "Arbolado", "views": [listado, iconos, partes]}]
            )

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
        elif ruta == "/api/v1/layer-views/9/":
            self._json(VISTA_HEXAGONOS)
        elif ruta == "/api/v1/layer-views/10/":
            self._json(VISTA_CALOR)
        elif ruta == "/api/v1/layer-views/11/":
            self._json(VISTA_CONTORNOS)
        elif ruta == "/api/v1/layer-views/12/":
            self._json(VISTA_POR_PARTES)

        elif ruta == "/api/v1/layer-views/7/":
            self._json(VISTA_TILOS)

        elif ruta == "/api/v1/layer-attributes/" and consulta.get("layer_id") == ["999"]:
            # Una capa borrada en GCC.
            self._json({"detail": "No encontrado."}, 404)

        elif ruta == "/api/v1/layer-attributes/" and consulta.get("layer_id") == ["51"]:
            # Como devel con una capa de un mapa sin permiso: lista vacía, sin 403.
            self._json([])

        elif ruta == "/api/v1/layer-attributes/" and consulta.get("layer_id") == ["50"]:
            # Una capa de un mapa sin permiso.
            self._json({"detail": "No tiene permiso para ver esta capa."}, 403)

        elif ruta == "/api/v1/layer-attributes/" and consulta.get("layer_id", [""])[0] in self.server.definiciones_extra:
            self._json(self.server.definiciones_extra[consulta["layer_id"][0]])

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
            self._json(_pagina_de_elementos(consulta, servidor=self.server))

        elif re.fullmatch(r"/api/v1/geodata/\d+/", ruta):
            fid = int(ruta.split("/")[-2])
            elemento = next((e for e in ELEMENTOS if e["properties"]["id"] == fid), None)
            if elemento is None or consulta.get("geometry_type") != ["points"]:
                self._json({"error": "no"}, 404)
            else:
                detalle = DETALLES.get(fid, {"pictures": [], "files": []})
                if consulta.get("embed_images") == ["false"]:
                    # Como el backend: enlaces a la API en vez de las fotos.
                    detalle = {
                        "pictures": [
                            {k: v for k, v in f.items() if k != "data"}
                            | {"url": f"/api/v1/geodata/image/{f['id']}/",
                               "thumbnail_url": f"/api/v1/geodata/image/{f['id']}/?as_thumbnail=1"}
                            for f in detalle["pictures"]
                        ],
                        "files": [f | {"url": f"/api/v1/geodata/file/{f['id']}/"} for f in detalle["files"]],
                    }
                self._json({**elemento, "id": fid, **detalle})

        elif re.fullmatch(r"/api/v1/geodata/image/\d+/", ruta):
            self._bytes(MINIATURA_PNG if consulta.get("as_thumbnail") == ["1"] else FOTO_PNG, "image/png")

        elif ruta == "/api/v1/geodata/file/31/":
            self._bytes(FICHERO_PDF, "application/pdf")

        elif ruta.startswith("/api/v1/additional-information/image/"):
            self._bytes(FOTO_PNG, "image/png")

        elif ruta == "/api/v1/additional-information/":
            # Sin el tipo de geometría la API no sabe en qué tabla buscar.
            if consulta.get("geometry_type") != ["Point"]:
                self._json({"results": [], "pagination": {"total_items": 0}})
            else:
                self._json(_pagina_de_partes(consulta))

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

    def _cortar(self):
        self.close_connection = True
        self.connection.shutdown(2)

    def do_POST(self):
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
            self._json(_pagina_de_elementos(consulta, datos.get("lasso_geometry"), servidor=self.server))
            return

        if partes.path == "/api/v1/geodata/adjuntos/":
            Handler.peticiones.append((partes.path, {k: v for k, v in datos.items() if k != "datos"}))
            if self.headers.get("Authorization") != "Token tok-de-prueba":
                self._json({"detail": "Credenciales no válidas"}, 401)
                return
            estado, cuerpo = self.server.subir_adjunto(datos)
            self._json(cuerpo, estado)
            return

        if partes.path == "/api/v1/geodata/confirmar/":
            Handler.peticiones.append((partes.path, datos))
            if self.headers.get("Authorization") != "Token tok-de-prueba":
                self._json({"detail": "Credenciales no válidas"}, 401)
                return
            lote_id = datos.get("lote_id")
            visto = self.server.lotes_vistos.get(lote_id) if lote_id else None
            if isinstance(visto, dict):
                if self.server.perder_respuesta:
                    self._cortar()
                    return
                self._json(visto)
                return
            if isinstance(visto, str) and self.server.tareas[visto][2] is None:
                self._json({"task_id": visto, "status_url": f"/api/v1/tasks/{visto}/status/"}, 202)
                return
            total = sum(len(datos.get(k) or []) for k in ("crear", "cambiar", "retirar"))
            sincrono = self.server.lote_sincrono
            if sincrono is not None and total > sincrono:
                tarea = f"tarea-{len(self.server.tareas) + 1}"
                self.server.tareas[tarea] = [datos, self.server.vueltas_de_tarea, None]
                if lote_id:
                    self.server.lotes_vistos[lote_id] = tarea
                self._json({
                    "method": "celery", "task_id": tarea,
                    "status_url": f"/api/v1/tasks/{tarea}/status/", "total": total,
                }, 202)
                return
            estado, cuerpo = self.server.confirmar(datos)
            if lote_id and estado == 200:
                self.server.lotes_vistos[lote_id] = cuerpo
            if self.server.perder_respuesta:
                # Entró, pero la conexión se cierra sin responder.
                self._cortar()
                return
            self._json(cuerpo, estado)
            return

        importar = re.match(r"^/api/v1/maps/(\d+)/layers/importar/(?:([^/]+)/confirmar/)?$", partes.path)
        if importar:
            Handler.peticiones.append((partes.path, datos))
            if importar.group(2):
                estado, cuerpo = _confirmar_importacion(self.server, importar.group(2))
            else:
                estado, cuerpo = _abrir_importacion(self.server, int(importar.group(1)), datos)
            self._json(cuerpo, estado)
            return

        crear = re.match(r"^/api/v1/maps/(\d+)/layers/crear/$", partes.path)
        if crear:
            Handler.peticiones.append((partes.path, datos))
            if self.headers.get("Authorization") != "Token tok-de-prueba":
                self._json({"detail": "Credenciales no válidas"}, 401)
                return
            estado, cuerpo = _capa_creada(self.server, int(crear.group(1)), datos)
            self._json(cuerpo, estado)
            return

        if partes.path == "/users/login/" and datos.get("email") == "provisional@ejemplo.com":
            # Como el backend: entra, pero con la contraseña marcada para cambiar.
            self._json(
                {
                    "api_token": "tok-provisional",
                    "jwt_token": "jwt-provisional",
                    "user": {"email": "provisional@ejemplo.com"},
                    "requires_password_change": True,
                },
                202,
            )
            return

        if partes.path == "/api/v1/user-management/change-own-password/":
            Handler.peticiones.append((partes.path, datos))
            if self.headers.get("Authorization") != "Token tok-provisional":
                self._json({"detail": "Credenciales no válidas"}, 401)
                return
            if datos.get("current_password") != "provisional":
                self._json({"error": "La contraseña actual es incorrecta"}, 400)
                return
            if len(datos.get("new_password") or "") < 12:
                self._json({"new_password": ["La contraseña debe tener al menos 12 caracteres."]}, 400)
                return
            # El cambio revoca el token anterior y el servidor da uno nuevo.
            self._json({"success": True, "api_token": "tok-nuevo", "jwt_token": "jwt-nuevo"})
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


    def do_PUT(self):
        partes = urlparse(self.path)
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo)
        trozo = re.match(r"^/api/v1/maps/\d+/layers/importar/([^/]+)/trozos/(\d+)/$", partes.path)
        if not trozo:
            self._json({"detail": "No existe"}, 404)
            return
        Handler.peticiones.append((partes.path, {"bytes": len(cuerpo)}))
        numero = int(trozo.group(2))
        if numero in self.server.cortar_trozos:
            # Se pierde por el camino una vez: no llega al servidor.
            self.server.cortar_trozos.discard(numero)
            self._cortar()
            return
        imp = self.server.importaciones.get(trozo.group(1))
        if imp is None:
            self._json({"error": "No encuentro esa importación."}, 404)
            return
        imp["trozos"][numero] = cuerpo
        self._json(_importacion(self.server, trozo.group(1))[1])

    def do_DELETE(self):
        partes = urlparse(self.path)
        Handler.peticiones.append((partes.path, {}))
        importacion = re.match(r"^/api/v1/maps/\d+/layers/importar/([^/]+)/$", partes.path)
        imp = self.server.importaciones.get(importacion.group(1)) if importacion else None
        if imp is None:
            self._json({"error": "No encuentro esa importación."}, 404)
            return
        imp["estado"] = "cancelada"
        self._json(_importacion(self.server, importacion.group(1))[1])


def _abrir_importacion(servidor, map_id, datos):
    """Como POST /maps/<id>/layers/importar/ (services/importar_capa.py del backend)."""
    if servidor.sin_layer_create:
        return 403, {"error": "No tienes permiso para crear capas en este mapa."}
    if any("__" in str(c.get("name", "")) for c in datos.get("campos") or []):
        return 400, {"error": "Un nombre de campo no puede llevar dos _ seguidos."}
    if _nombre_usado(servidor, datos.get("name")):
        return 409, {"error": f"Ya hay una capa «{datos['name']}» en este mapa. Elige otro nombre."}
    if any(imp["estado"] in ("subiendo", "importando") for imp in servidor.importaciones.values()):
        return 409, {"error": "Ya tienes una importación en marcha. Espera a que acabe o cancélala."}
    id_subida = f"sub-{len(servidor.importaciones) + 1}"
    servidor.importaciones[id_subida] = {
        "map_id": map_id, "datos": datos, "trozos": {}, "estado": "subiendo", "creada": time.time(),
        "vueltas": servidor.vueltas_importando, "capa_id": None, "error": None,
    }
    return 201, _importacion(servidor, id_subida)[1]


def _importacion(servidor, id_subida, avanzar=False):
    imp = servidor.importaciones.get(id_subida)
    if imp is None:
        return 404, {"error": "No encuentro esa importación."}
    if avanzar and imp["estado"] == "importando":
        imp["vueltas"] -= 1
        if imp["vueltas"] <= 0:
            imp["estado"] = imp.pop("final", "hecha")
    tamano, trozo = imp["datos"]["tamano"], servidor.trozo
    total = -(-tamano // trozo)
    hechos = len(servidor.elementos_de_capa.get(imp["capa_id"], [])) if imp["capa_id"] else 0
    return 200, {
        "id": id_subida, "map_id": imp["map_id"], "nombre": imp["datos"].get("name"), "estado": imp["estado"],
        "tamano": tamano, "trozo": trozo, "trozos": total,
        "creada": imp.get("creada"), "ultima_actividad": imp.get("creada"),
        "faltan": [n for n in range(total) if n not in imp["trozos"]],
        "progreso": {"hechos": hechos if imp["estado"] == "hecha" else 0, "total": imp["datos"].get("elementos")},
        "capa_id": imp["capa_id"] if imp["estado"] == "hecha" else None, "error": imp["error"],
    }


def _confirmar_importacion(servidor, id_subida):
    """Como POST …/importar/<id>/confirmar/: comprueba la huella, crea la capa y lee el
    GeoPackage como lo importaría el servidor."""
    from qgis.core import QgsVectorLayer

    imp = servidor.importaciones.get(id_subida)
    if imp is None:
        return 404, {"error": "No encuentro esa importación."}
    if imp["estado"] != "subiendo":
        return 409, {"error": "Esta importación ya está confirmada."}
    fichero = b"".join(imp["trozos"][n] for n in sorted(imp["trozos"]))
    if hashlib.sha256(fichero).hexdigest() != imp["datos"]["huella"]:
        imp["estado"], imp["error"] = "fallida", "El fichero llegó distinto del que se mandó."
        return 409, {"error": imp["error"]}
    datos = imp["datos"]
    estado, capa = _capa_creada(
        servidor, imp["map_id"], {k: datos[k] for k in ("name", "geometry_type", "campos")}, al_importar=True
    )
    if estado != 201:
        return estado, capa
    imp["capa_id"] = capa["id"]
    with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as f:
        f.write(fichero)
    try:
        leida = QgsVectorLayer(f"{f.name}|layername=capa", "importada", "ogr")
        servidor.elementos_de_capa[capa["id"]] = [
            {"geometry": json.loads(e.geometry().asJson()),
             "properties": {c.name(): e[c.name()] for c in leida.fields() if c.name() != "fid"}}
            for e in leida.getFeatures()
        ]
        del leida
    finally:
        os.remove(f.name)
    imp["estado"] = "importando"
    return 202, _importacion(servidor, id_subida)[1]


TODOS_LOS_PERMISOS = {"can_create": True, "can_update": True, "can_retire": True, "update_restringido": False}
SIN_PERMISOS = {"can_create": False, "can_update": False, "can_retire": False, "update_restringido": False}


class _Servidor(HTTPServer):
    """El servidor con su estado: los elementos, sus versiones y los permisos.

    Cada prueba tiene los suyos (una copia de ``ELEMENTOS``), porque confirmar
    los cambia.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.elementos = copy.deepcopy(ELEMENTOS)
        self.versiones = {
            e["properties"]["id"]: f"2026-08-0{i + 1}T10:00:00.12345{i}+00:00"
            for i, e in enumerate(self.elementos)
        }
        self.permisos = {11: dict(TODOS_LOS_PERMISOS)}
        self.lotes = []
        # (estado, cuerpo) que dará la próxima confirmación, sin aplicar nada.
        self.forzar = None
        # Los campos calculados que pone el servidor: (antes, nuevos) → {campo: valor}.
        self.calcular = lambda antes, nuevos: {}
        self._siguiente_id = 2001
        # Capas creadas con maps/<id>/layers/crear/: sus elementos, aparte.
        self.elementos_de_capa = {}
        self.sin_layer_create = False
        # Importaciones a trozos: id → estado; trozos que se pierden una vez; las vueltas
        # que pasa «importando» antes de acabar.
        self.importaciones = {}
        self.cortar_trozos = set()
        self.vueltas_importando = 2
        self.trozo = 40_000
        self._reloj = 0
        # Las fotos y los ficheros subidos sueltos para un alta: ref → datos.
        self.adjuntos = {}
        # Lo que cada alta se quedó: id → {campo: [(nombre, bytes)]}.
        self.adjuntos_de = {}
        # Como LOTE_SINCRONO del backend: por encima, 202 y el lote en segundo plano.
        # None: todo síncrono. Las tareas: id → [lote, vueltas que quedan, resultado].
        self.lote_sincrono = None
        self.vueltas_de_tarea = 2
        self.tareas = {}
        # Como LoteDeQgis: lote_id → respuesta de los lotes que entraron, o la tarea en curso.
        self.lotes_vistos = {}
        # Las confirmaciones se aplican pero la respuesta no llega (un corte), hasta que la
        # prueba lo quite: Qt repite por su cuenta la petición cuando se cierra la conexión.
        self.perder_respuesta = False

    def _version_nueva(self):
        self._reloj += 1
        return f"2026-10-11T12:00:{self._reloj:02d}.{self._reloj:06d}+00:00"

    def tocar(self, fid, **atributos):
        """Otro usuario cambia el elemento: nueva versión."""
        elemento = next(e for e in self.elementos if e["properties"]["id"] == fid)
        elemento["properties"].update(atributos)
        self.versiones[fid] = self._version_nueva()

    def subir_adjunto(self, datos):
        """Como POST /geodata/adjuntos/: campo de fotos o ficheros del esquema y permiso de alta."""
        if not self.permisos.get(datos.get("layer_id"), SIN_PERMISOS)["can_create"]:
            return 403, {"error": "No tiene permisos para create en esta capa"}
        tipos = {a["name"]: a["type"] for a in _campos_del_esquema(ESQUEMA_ARBOLADO.get("attributes"))}
        campo = datos.get("campo")
        if tipos.get(campo) not in ("images", "files"):
            return 400, {"error": f"«{campo}» no es un campo de fotos ni de ficheros de la capa", "campo": campo}
        nombre = datos.get("nombre") or ""
        if nombre.lower().endswith(".exe"):
            return 400, {"error": f"«{nombre}»: el tipo de archivo .exe no está permitido"}
        ref = f"00000000-0000-0000-0000-{len(self.adjuntos) + 1:012d}"
        self.adjuntos[ref] = {
            "campo": campo, "nombre": nombre, "contenido": base64.b64decode(datos.get("datos") or ""),
            "tipo": "foto" if tipos[campo] == "images" else "fichero",
        }
        return 201, {
            "adjunto": ref, "campo": campo, "tipo": self.adjuntos[ref]["tipo"], "nombre": nombre,
            "tamano": len(self.adjuntos[ref]["contenido"]), "caduca": "2026-10-16T12:00:00+00:00",
        }

    def _resolver_adjuntos(self, atributos):
        """Como ``adjuntos_pendientes.resolver``: las referencias, por su contenido."""
        usados = {}
        for campo, valor in list(atributos.items()):
            if not isinstance(valor, list) or not any(isinstance(v, dict) and "adjunto" in v for v in valor):
                continue
            for v in valor:
                adjunto = self.adjuntos.get(v.get("adjunto")) if isinstance(v, dict) else None
                if adjunto is None or adjunto["campo"] != campo:
                    return None, {"campo": campo, "error": f"«{campo}»: un adjunto ya no está en Geosian"}
                usados.setdefault(campo, []).append((v["adjunto"], adjunto["nombre"], adjunto["contenido"]))
            del atributos[campo]
        return usados, None

    def _confirmar_en_capa_nueva(self, lote):
        """Altas en una capa creada en la prueba: todas o ninguna, sin reglas del arbolado."""
        if lote.get("cambiar") or lote.get("retirar"):
            return 400, {"errores": [{"error": "En la capa nueva de prueba solo hay altas"}]}
        lista = self.elementos_de_capa[lote["layer_id"]]
        creados = []
        for alta in lote.get("crear", []):
            fid = self._siguiente_id
            self._siguiente_id += 1
            lista.append({
                "type": "Feature", "geometry": alta["geometry"],
                "properties": {"id": fid, "object_id": f"OBJ-{fid}", **(alta.get("attributes") or {})},
            })
            self.versiones[fid] = self._version_nueva()
            creados.append({"ref": alta["ref"], "id": fid, "object_id": f"OBJ-{fid}",
                            "updated_at": self.versiones[fid], "calculados": {}})
        return 200, {"creados": creados, "cambiados": [], "retirados": []}

    def confirmar(self, lote):
        """Como POST /geodata/confirmar/: todo o nada, con el mismo cuerpo de respuesta."""
        self.lotes.append(copy.deepcopy(lote))
        if self.forzar is not None:
            estado, cuerpo = self.forzar
            self.forzar = None
            return estado, cuerpo
        if lote.get("layer_id") in self.elementos_de_capa:
            return self._confirmar_en_capa_nueva(lote)
        permisos = self.permisos.get(lote.get("layer_id"), SIN_PERMISOS)
        if (lote.get("crear") and not permisos["can_create"]) or (
            lote.get("cambiar") and not permisos["can_update"]
        ) or (lote.get("retirar") and not permisos["can_retire"]):
            return 403, {"error": "No tiene permisos para update en esta capa"}

        por_id = {e["properties"]["id"]: e for e in self.elementos}
        errores, choques = [], []
        for nombre in ("cambiar", "retirar"):
            for op in lote.get(nombre, []):
                if op["id"] not in por_id:
                    errores.append({"op": nombre, "id": op["id"], "error": "El elemento no existe en esta capa"})
                elif op.get("expected_updated_at") != self.versiones[op["id"]]:
                    choques.append({
                        "op": nombre, "id": op["id"], "updated_at": self.versiones[op["id"]],
                        "object_status": "disponible",
                        "updated_by": {"id": 7, "username": "otra", "nombre": "Otra Técnica"},
                    })
        if errores:
            return 400, {"errores": errores}
        if choques:
            return 409, {"conflictos": choques}
        for op in lote.get("cambiar", []):
            if "attributes" in op:
                error = _reglas_de_la_web(por_id[op["id"]]["properties"], dict(op["attributes"]), False)
                if error:
                    return 400, {"errores": [{"op": "cambiar", "id": op["id"], **error}]}
        medios = {}
        for alta in lote.get("crear", []):
            usados, error = self._resolver_adjuntos(alta.setdefault("attributes", {}))
            if error:
                return 400, {"errores": [{"op": "crear", "ref": alta.get("ref"), **error}]}
            medios[alta.get("ref")] = usados
            error = _reglas_de_la_web({}, alta["attributes"], True)
            if error:
                return 400, {"errores": [{"op": "crear", "ref": alta.get("ref"), **error}]}

        resultado = {"creados": [], "cambiados": [], "retirados": []}
        for op in lote.get("cambiar", []):
            propiedades = por_id[op["id"]]["properties"]
            calculados = self.calcular(dict(propiedades), op["attributes"]) if "attributes" in op else {}
            propiedades.update({**(op.get("attributes") or {}), **calculados})
            if "geometry" in op:
                por_id[op["id"]]["geometry"] = op["geometry"]
            self.versiones[op["id"]] = self._version_nueva()
            resultado["cambiados"].append({
                "id": op["id"], "updated_at": self.versiones[op["id"]], "calculados": calculados,
            })
        for op in lote.get("retirar", []):
            self.elementos.remove(por_id[op["id"]])
            self.versiones[op["id"]] = self._version_nueva()
            resultado["retirados"].append({"id": op["id"], "updated_at": self.versiones[op["id"]]})
        for alta in lote.get("crear", []):
            fid = self._siguiente_id
            self._siguiente_id += 1
            calculados = self.calcular({}, alta.get("attributes") or {})
            self.elementos.append({
                "type": "Feature", "geometry": alta["geometry"],
                "properties": {"id": fid, "object_id": f"OBJ-{fid}", **(alta.get("attributes") or {}), **calculados},
            })
            self.versiones[fid] = self._version_nueva()
            if medios.get(alta["ref"]):
                self.adjuntos_de[fid] = {
                    campo: [(nombre, contenido) for _, nombre, contenido in lista]
                    for campo, lista in medios[alta["ref"]].items()
                }
                for lista in medios[alta["ref"]].values():
                    for ref, _, _ in lista:
                        self.adjuntos.pop(ref, None)
            resultado["creados"].append({
                "ref": alta["ref"], "id": fid, "object_id": f"OBJ-{fid}", "updated_at": self.versiones[fid],
                "calculados": calculados,
            })
        return 200, resultado


def _nombre_usado(servidor, nombre):
    """Como el ``name__iexact`` del backend, entre las capas del mapa del servidor falso."""
    nombre = str(nombre or "").strip().casefold()
    return any(str(c.get("name")).casefold() == nombre for c in CAPAS + servidor.capas_extra)


def _capa_creada(servidor, map_id, datos, al_importar=False):
    """Como POST /maps/<id>/layers/crear/ (services/crear_capa.py del backend)."""
    if servidor.sin_layer_create:
        return 403, {"error": "No tienes permiso para crear capas en este mapa."}
    nombre = str(datos.get("name") or "").strip()
    if not nombre:
        return 400, {"error": "Ponle un nombre a la capa."}
    if not al_importar and _nombre_usado(servidor, nombre):
        return 409, {"error": f"Ya hay una capa «{nombre}» en este mapa. Elige otro nombre."}
    if ("plantilla" in datos) == ("campos" in datos):
        return 400, {"error": "Elige una forma: a partir de otra capa (plantilla) o con campos."}
    if "plantilla" in datos:
        if datos["plantilla"] != 11:
            return 404, {"error": "No encuentro esa capa, o no tienes permiso para verla."}
        tipo, esquema = "Point", copy.deepcopy(ESQUEMA_ARBOLADO)
    else:
        tipo = datos.get("geometry_type")
        if tipo not in ("Point", "MultiPoint", "MultiLineString", "MultiPolygon"):
            return 400, {"error": f"Tipo de geometría no admitido: {tipo!r}."}
        esquema = {"name": nombre.lower(), "title": nombre, "attributes": datos["campos"]}
    capa_id = 300 + len(servidor.elementos_de_capa)
    capa = {"id": capa_id, "name": nombre, "map": map_id, "description": "Creada desde QGIS.", "tile_version": 0}
    servidor.capas_extra.append(capa)
    servidor.definiciones_extra[str(capa_id)] = [
        {"id": 900 + capa_id, "layer": capa_id, "geometry_type": tipo, "schema": esquema}
    ]
    servidor.permisos[capa_id] = dict(TODOS_LOS_PERMISOS)
    servidor.elementos_de_capa[capa_id] = []
    return 201, {**capa, "permissions": dict(TODOS_LOS_PERMISOS), "geometry_types": [tipo]}


def _campos_del_esquema(atributos):
    for attr in atributos or []:
        if attr.get("type") in ("section", "section_decision", "page_section"):
            yield from _campos_del_esquema(attr.get("contents"))
        elif attr.get("name"):
            yield attr


def _reglas_de_la_web(antes, nuevos, alta):
    """Como ``reglas_de_la_web`` del backend: lo que la web no deja, en el lote.

    Devuelve el error (o None); las altas se corrigen en ``nuevos``.
    """
    nodos = {}
    for attr in _campos_del_esquema(ESQUEMA_ARBOLADO.get("attributes")):
        nodos.setdefault(attr["name"], []).append(attr)
    for nombre, lista in nodos.items():
        if not all(a.get("editable") is False or a.get("visible") is False for a in lista):
            continue
        if alta:
            nuevos.pop(nombre, None)
        elif nombre in nuevos and nuevos[nombre] != antes.get(nombre):
            return {"campo": nombre, "error": f"«{nombre}» es de solo lectura en Geosian: no se cambia"}

    def como_lista(valor):
        return [] if valor in (None, "") else valor if isinstance(valor, list) else [valor]

    for nombre, valor in nuevos.items():
        lista = nodos.get(nombre) or []
        if not lista or any(
            a.get("type") not in ("select", "radio", "checkbox", "autocomplete")
            or not isinstance(a.get("allowed_values"), list)
            for a in lista
        ):
            continue
        permitidos = {str(v) for a in lista for v in a["allowed_values"]}
        ya = set() if alta else {str(v) for v in como_lista(antes.get(nombre))}
        fuera = [v for v in como_lista(valor) if str(v) not in permitidos and str(v) not in ya]
        if permitidos and fuera:
            return {"campo": nombre, "error": f"«{nombre}»: «{fuera[0]}» no está en su lista de valores en Geosian"}

    # Obligatorios, simplificado al esquema de aquí: en un alta, los de primer nivel.
    if alta:
        for attr in ESQUEMA_ARBOLADO.get("attributes") or []:
            if attr.get("required") is True and attr.get("editable") is not False and nuevos.get(attr["name"]) in (None, ""):
                return {"campo": attr["name"], "error": f"«{attr['name']}» es obligatorio en Geosian"}
    return None


class FakeGeosian:
    """Servidor de usar y tirar, en un hilo aparte."""

    def __init__(self):
        Handler.peticiones = []
        self._server = _Servidor(("127.0.0.1", 0), Handler)
        # El tile_config de /maps/<id>/layers/; None, el de un servidor que no lo da.
        self._server.tile_config = None
        # Capas que añade una prueba al mapa 4, con sus definiciones por id de capa.
        self._server.capas_extra = []
        self._server.definiciones_extra = {}
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

    def poner_tile_config(self, config):
        self._server.tile_config = config

    def poner_capa(self, capa, definiciones):
        self._server.capas_extra.append(capa)
        self._server.definiciones_extra[str(capa["id"])] = definiciones

    @property
    def estado(self):
        """El estado del servidor: ``elementos``, ``versiones``, ``permisos``, ``lotes``…"""
        return self._server

    def rutas_pedidas(self):
        return [ruta for ruta, _ in Handler.peticiones]
