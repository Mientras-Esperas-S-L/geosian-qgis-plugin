"""Vistas agregadas con las teselas que agrega el servidor, sin QGIS delante.

La web, sobre una capa grande, no baja los puntos para las vistas de hexágonos: pide
al servidor teselas vectoriales ya agregadas
(``/api/v1/geodata/tiles/{z}/{x}/{y}.mvt?layer_id=…&agg=hex``) con la cabecera
``Authorization: Token …``. Cada tesela trae una capa ``agg`` con un hexágono por
celda y su ``count`` (y ``weight``, ``lng``, ``lat`` y ``density`` según se pida). El
lado del hexágono lo pone el servidor según el zoom.

El color sigue a ``useMvtLayers.js``: rampa de seis colores en escala logarítmica,
``t = min(1, ln(1+count)/ln(1+colorMax))`` y el color ``floor(t·6)``.
"""

import math
from urllib.parse import quote, urlencode

from .client import API_PREFIX

# Las visualizaciones que la web pinta con las teselas agregadas del servidor.
HEXAGONOS = ("hexagon", "h3hexagon")
# El calor de una capa grande: celdas finas del servidor, como la web en móvil
# (``heatcells``: ``cells=96``), coloreadas como los hexágonos.
CELDAS_DE_CALOR = 96
# Hasta qué zoom pide teselas QGIS; de ahí arriba amplía las que tiene.
ZOOM_MAXIMO = 18
CAPA_MVT = "agg"


def tile_url(base_url, layer_id, params=None, extra=None):
    """La plantilla ``{z}/{x}/{y}`` de las teselas agregadas, con sus filtros."""
    consulta = [("layer_id", layer_id), ("agg", "hex")]
    for clave, valor in (extra or {}).items():
        consulta.append((clave, valor))
    for clave, valor in (params or {}).items():
        for v in valor if isinstance(valor, (list, tuple)) else [valor]:
            consulta.append((clave, v))
    return (
        f"{base_url.rstrip('/')}{API_PREFIX}/geodata/tiles/{{z}}/{{x}}/{{y}}.mvt?"
        + urlencode(consulta)
    )


def tile_layer_uri(base_url, layer_id, params, authcfg, extra=None):
    """La URI de una capa de teselas vectoriales de QGIS para esas teselas.

    La credencial no va aquí: va en el ``authcfg`` (una cabecera guardada en el
    gestor de autenticación de QGIS), así que el proyecto no la lleva dentro.
    """
    url = quote(tile_url(base_url, layer_id, params, extra), safe=":/{}")
    uri = f"type=xyz&url={url}&zmin=0&zmax={ZOOM_MAXIMO}"
    if authcfg:
        uri += f"&authcfg={authcfg}"
    return uri


# Lo que una capa agregada guarda de sí misma (en una propiedad de la capa) para que
# el tiempo real la encuentre y la vuelva a pedir.
PROPIEDAD = "geosian/agregada"


def describe(conexion, map_id, layer_id, base_url, params, authcfg, extra=None):
    return {
        "conexion": conexion, "map_id": int(map_id), "layer_id": int(layer_id),
        "base_url": base_url, "params": params or {}, "authcfg": authcfg,
        "extra": extra or {},
    }


def uri_for(info, version=None):
    """La URI de una capa agregada; con ``version``, la de esas teselas (``_v``)."""
    extra = dict(info.get("extra") or {})
    if version is not None:
        extra["_v"] = version
    return tile_layer_uri(info["base_url"], info["layer_id"], info["params"], info["authcfg"], extra)


def count_bucket(count, color_max):
    """El color (0 a 5) de una celda con ``count`` puntos."""
    color_max = max(float(color_max or 100), 1.0)
    t = min(1.0, math.log1p(max(float(count or 0), 0.0)) / math.log1p(color_max))
    return min(5, int(t * 6))


def count_bucket_expression(color_max):
    """La expresión de QGIS que da el tramo (0 a 5) de una celda por su ``count``."""
    color_max = max(float(color_max or 100), 1.0)
    return (
        "min(5, floor(min(1, ln(1 + max(coalesce(\"count\", 0), 0))"
        f" / ln(1 + {color_max:g})) * 6))"
    )


def count_color_expression(rampa, color_max):
    """La expresión de QGIS que da el color de una celda por su ``count``."""
    casos = " ".join(
        f"WHEN @i = {i} THEN '{r},{g},{b},{a}'" for i, (r, g, b, a) in enumerate(rampa[:6])
    )
    return f"with_variable('i', {count_bucket_expression(color_max)}, CASE {casos} END)"


# Las etiquetas de la leyenda de la web para las agregadas, en los extremos.
LEYENDA = ("Baja densidad", "", "", "", "", "Alta densidad")


# Contornos: los centroides de las celdas del servidor, a un zoom en que cada celda mida
# la mitad de ``cellSize``. Como mucho estas teselas por cálculo; si no caben, menos zoom.
MAX_TESELAS = 64
_MUNDO = 40075016.686


def contour_tiles(bbox, cell_size, maximo=MAX_TESELAS):
    """``(z, [(x, y), …])`` de las teselas que cubren ``bbox`` (grados)."""
    oeste, sur, este, norte = bbox
    objetivo = max(float(cell_size or 200) / 2, 1.0)
    z = round(math.log2(_MUNDO / (objetivo * CELDAS_DE_CALOR)))
    z = max(0, min(ZOOM_MAXIMO, z))
    while True:
        x0, y1 = _tesela(oeste, sur, z)
        x1, y0 = _tesela(este, norte, z)
        teselas = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        if len(teselas) <= maximo or z == 0:
            return z, teselas
        z -= 1


def tile_bounds(z, x, y):
    """``(oeste, sur, este, norte)`` de una tesela, en metros de EPSG:3857."""
    lado = _MUNDO / 2 ** z
    oeste = -_MUNDO / 2 + x * lado
    norte = _MUNDO / 2 - y * lado
    return oeste, norte - lado, oeste + lado, norte


def tiles_in_extent(extension, z):
    """``[(x, y), …]`` de las teselas de zoom ``z`` que cubren ``extension`` (EPSG:3857)."""
    oeste, sur, este, norte = extension
    n = 2 ** z
    lado = _MUNDO / n

    def columna(v):
        return min(max(int((v + _MUNDO / 2) // lado), 0), n - 1)

    def fila(v):
        return min(max(int((_MUNDO / 2 - v) // lado), 0), n - 1)

    return [(x, y) for x in range(columna(oeste), columna(este) + 1)
            for y in range(fila(norte), fila(sur) + 1)]


def polygons_in_mercator(anillos, z, x, y, extension=4096):
    """Los polígonos de una geometría MVT de la tesela ``z/x/y``, en EPSG:3857.

    ``[[exterior, hueco, …], …]``: un anillo con área positiva en coordenadas de la
    tesela (el exterior, según la especificación MVT) abre polígono; uno negativo es un
    hueco del anterior. Los puntos fuera de [0, extensión] se respetan: el servidor no
    recorta las celdas.
    """
    oeste, _, este, norte = tile_bounds(z, x, y)
    escala = (este - oeste) / float(extension)
    poligonos = []
    for anillo in anillos:
        if len(anillo) < 3:
            continue
        area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(anillo, anillo[1:] + anillo[:1]))
        enmetros = [(oeste + px * escala, norte - py * escala) for px, py in anillo]
        if area > 0 or not poligonos:
            poligonos.append([enmetros])
        else:
            poligonos[-1].append(enmetros)
    return poligonos


def _tesela(lon, lat, z):
    n = 2 ** z
    lat = max(min(lat, 85.0511), -85.0511)
    x = int((lon + 180.0) / 360.0 * n)
    r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def to_mercator(lon, lat):
    x = lon * 20037508.342789244 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * 6378137.0
    return x, y


def cell_points(celdas, por_peso):
    """``(x, y, peso)`` en metros (EPSG:3857) de las celdas con ``lng`` y ``lat``.

    El peso es ``count``, o ``weight`` si la vista pesa por un atributo.
    """
    puntos = []
    for celda in celdas:
        lon, lat = celda.get("lng"), celda.get("lat")
        if lon is None or lat is None:
            continue
        peso = celda.get("weight") if por_peso else None
        if peso is None:
            peso = celda.get("count") or 0
        x, y = to_mercator(float(lon), float(lat))
        puntos.append((x, y, peso))
    return puntos
