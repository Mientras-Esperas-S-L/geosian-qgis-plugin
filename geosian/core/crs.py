"""El sistema en metros para abrir las capas de GreenCityControl.

GreenCityControl guarda en grados (EPSG:4326). Para medir en QGIS (un buffer de 10 m)
la capa tiene que estar en metros: en España, ETRS89 / UTM del huso que toca, que es
lo que se usa allí; fuera, WGS 84 / UTM.
"""

import math

# España: península, Baleares, Canarias, Ceuta y Melilla.
_ESPAÑA = (-18.5, 27.0, 4.6, 44.0)


def en_metros(lon, lat):
    """El ``authid`` del sistema UTM en metros para ese sitio, en grados."""
    huso = min(max(math.floor((lon + 180) / 6) + 1, 1), 60)
    oeste, sur, este, norte = _ESPAÑA
    if oeste <= lon <= este and sur <= lat <= norte:
        # ETRS89 / UTM 28N a 31N (Canarias en el 28).
        return f"EPSG:{25800 + min(max(huso, 28), 31)}"
    return f"EPSG:{(32600 if lat >= 0 else 32700) + huso}"
