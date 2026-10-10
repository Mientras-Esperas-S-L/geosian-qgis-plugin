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


def describe(conexion, map_id, layer_id, base_url, params, authcfg):
    return {
        "conexion": conexion, "map_id": int(map_id), "layer_id": int(layer_id),
        "base_url": base_url, "params": params or {}, "authcfg": authcfg,
    }


def uri_for(info, version=None):
    """La URI de una capa agregada; con ``version``, la de esas teselas (``_v``)."""
    extra = {"_v": version} if version is not None else None
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
