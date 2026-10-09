"""Mapas base como los de la web, sin QGIS delante.

El fondo por defecto de la web es «GEOSIAN»: teselas vectoriales propias
(OpenStreetMap con Planetiler, servidas por CT118 y publicadas en
``<aplicación>/teselas``) pintadas con un estilo de MapLibre que vive en el
código del frontal (``createOmtStyle`` en ``src/constants/map-providers.js``).
El estilo viaja con el complemento en ``resources/fondo_geosian.json``, copiado
de la web; si se cambia allí, hay que volver a copiarlo (ver su ``metadata``).

Además, cada mapa puede tener fondos propios dados de alta en la administración
(``basemaps`` del detalle del mapa).
"""

import json
import os
from urllib.parse import urlparse

# Si la API no se llama «api.algo», no se sabe dónde está la aplicación. Las
# teselas de producción son públicas, y son las que usa el frontal en local.
APP_POR_DEFECTO = "https://app.greencitycontrol.com"

_ESTILO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "fondo_geosian.json")


def app_origin(api_url):
    """Origen de la aplicación web que va con una API (``api.x`` → ``app.x``)."""
    partes = urlparse(api_url or "")
    host = partes.hostname or ""
    if not host.startswith("api."):
        return APP_POR_DEFECTO
    puerto = f":{partes.port}" if partes.port else ""
    return f"{partes.scheme or 'https'}://app.{host[len('api.'):]}{puerto}"


def geosian_style(api_url):
    """El estilo MapLibre del fondo GEOSIAN con las teselas de esa aplicación."""
    with open(_ESTILO, encoding="utf-8") as fichero:
        estilo = json.load(fichero)
    base = app_origin(api_url) + "/teselas"
    for fuente in estilo.get("sources", {}).values():
        fuente["tiles"] = [t.replace("{TESELAS}", base) for t in fuente.get("tiles", [])]
    return estilo


def layer_specs(fondos, api_url):
    """Los fondos propios del mapa como capas que QGIS sabe abrir.

    Returns:
        Lista de diccionarios: ``type`` ``raster`` (teselas z/x/y, también las de
        un WMS que la aplicación ya sirve así por su proxy) o ``style`` (un
        estilo de MapLibre con su URL). Los que no traen dirección se omiten.
    """
    capas = []
    for fondo in fondos or []:
        if not isinstance(fondo, dict):
            continue
        nombre = str(fondo.get("name") or fondo.get("code") or "Fondo")
        if fondo.get("style_url"):
            capas.append({"name": nombre, "type": "style", "url": fondo["style_url"]})
            continue
        teselas = fondo.get("tiles") or []
        if not teselas:
            continue
        url = teselas[0]
        if url.startswith("/"):
            # Ruta del proxy de la aplicación: la absolutiza el frontal contra su
            # propio origen, y aquí igual.
            url = app_origin(api_url) + url
        capas.append(
            {
                "name": nombre,
                "type": "raster",
                "url": url,
                "zmin": int(fondo.get("min_zoom") or 0),
                "zmax": int(fondo.get("max_zoom") or 19),
            }
        )
    return capas
