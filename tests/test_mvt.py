"""Lector mínimo de teselas MVT: las propiedades de las celdas agregadas."""

import gzip
import struct

from geosian.core import mvt

# Un codificador de protobuf aparte, a mano, para no probar el lector consigo mismo.


def _varint(n):
    salida = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            salida += bytes([b | 0x80])
        else:
            return salida + bytes([b])


def _campo(numero, tipo, cuerpo):
    return _varint((numero << 3) | tipo) + cuerpo


def _mensaje(numero, contenido):
    return _campo(numero, 2, _varint(len(contenido)) + contenido)


def _valor(v):
    if isinstance(v, str):
        return _mensaje(1, v.encode())
    if isinstance(v, float):
        return _campo(3, 1, struct.pack("<d", v))
    return _campo(5, 0, _varint(v))


def _tesela(nombre, objetos):
    claves, valores, cuerpos = [], [], b""
    for propiedades in objetos:
        etiquetas = b""
        for k, v in propiedades.items():
            if k not in claves:
                claves.append(k)
            valores.append(v)
            etiquetas += _varint(claves.index(k)) + _varint(len(valores) - 1)
        cuerpos += _mensaje(2, _campo(3, 0, _varint(3)) + _mensaje(2, etiquetas))
    capa = _campo(15, 0, _varint(2)) + _mensaje(1, nombre.encode()) + cuerpos
    capa += b"".join(_mensaje(3, k.encode()) for k in claves)
    capa += b"".join(_mensaje(4, _valor(v)) for v in valores)
    capa += _campo(5, 0, _varint(4096))
    return _mensaje(3, capa)


def test_lee_las_propiedades_de_las_celdas():
    datos = _tesela("agg", [{"count": 12, "lng": -3.7, "lat": 40.4, "weight": 30.5},
                            {"count": 3, "lng": -3.6, "lat": 40.5}])
    capas = mvt.decode(datos)
    assert capas["agg"] == [
        {"count": 12, "lng": -3.7, "lat": 40.4, "weight": 30.5},
        {"count": 3, "lng": -3.6, "lat": 40.5},
    ]


def test_tambien_comprimida_y_vacia():
    datos = _tesela("agg", [{"count": 1, "lng": 0.5, "lat": 0.5}])
    assert mvt.decode(gzip.compress(datos))["agg"][0]["count"] == 1
    assert mvt.decode(b"") == {}


def _zigzag(n):
    return (n << 1) ^ (n >> 31)


def _anillos(anillos):
    """Comandos MVT de un polígono (MoveTo, LineTo, ClosePath), cursor relativo."""
    comandos, cx, cy = [], 0, 0
    for anillo in anillos:
        (x0, y0), resto = anillo[0], anillo[1:]
        comandos += [(1 & 7) | (1 << 3), _zigzag(x0 - cx), _zigzag(y0 - cy)]
        cx, cy = x0, y0
        comandos.append((2 & 7) | (len(resto) << 3))
        for x, y in resto:
            comandos += [_zigzag(x - cx), _zigzag(y - cy)]
            cx, cy = x, y
        comandos.append((7 & 7) | (1 << 3))
    return b"".join(_varint(c) for c in comandos)


def _tesela_con_poligonos(nombre, objetos, extension=4096):
    claves, valores, cuerpos = [], [], b""
    for propiedades, anillos in objetos:
        etiquetas = b""
        for k, v in propiedades.items():
            if k not in claves:
                claves.append(k)
            valores.append(v)
            etiquetas += _varint(claves.index(k)) + _varint(len(valores) - 1)
        cuerpos += _mensaje(2, _campo(3, 0, _varint(3)) + _mensaje(2, etiquetas) + _mensaje(4, _anillos(anillos)))
    capa = _campo(15, 0, _varint(2)) + _mensaje(1, nombre.encode()) + cuerpos
    capa += b"".join(_mensaje(3, k.encode()) for k in claves)
    capa += b"".join(_mensaje(4, _valor(v)) for v in valores)
    capa += _campo(5, 0, _varint(extension))
    return _mensaje(3, capa)


def test_lee_los_poligonos_enteros_aunque_salgan_de_la_tesela():
    """El servidor manda cada hexágono entero (sin recortar) en la tesela de su centro: un
    lado puede quedar fuera de [0, extensión]."""
    hexagono = [(4000, 2000), (4150, 1900), (4300, 2000), (4300, 2200), (4150, 2300), (4000, 2200)]
    datos = _tesela_con_poligonos("agg", [({"count": 7}, [hexagono]), ({"count": 2}, [[(0, 0), (10, 0), (10, 10)]])])
    [celda, triangulo] = mvt.decode_features(datos)["agg"]
    assert celda["props"] == {"count": 7}
    assert celda["extent"] == 4096
    assert celda["rings"] == [hexagono]
    assert triangulo["rings"] == [[(0, 0), (10, 0), (10, 10)]]
    # La lectura de propiedades sigue igual.
    assert mvt.decode(datos)["agg"] == [{"count": 7}, {"count": 2}]


def test_las_celdas_de_una_tesela_en_metros():
    from geosian.core import aggregated

    # La tesela 0/0/0 es el mundo entero: su esquina noroeste y su centro.
    oeste, _, este, norte = aggregated.tile_bounds(0, 0, 0)
    assert round(oeste) == -20037508 and round(norte) == 20037508 and round(este) == 20037508
    [[anillo]] = aggregated.polygons_in_mercator([[(0, 0), (4096, 0), (4096, 4096)]], 0, 0, 0)
    assert [tuple(round(v) for v in p) for p in anillo] == [(-20037508, 20037508), (20037508, 20037508), (20037508, -20037508)]
    # Un lado fuera de la tesela se queda fuera: no se recorta.
    [[anillo]] = aggregated.polygons_in_mercator([[(4000, 0), (4300, 0), (4300, 100)]], 1, 0, 0)
    assert max(p[0] for p in anillo) > aggregated.tile_bounds(1, 0, 0)[2]
    # Teselas que cubren un rectángulo pequeño en Madrid a z=13: unas pocas, y la suya.
    x, y = aggregated._tesela(-3.70, 40.42, 13)
    cx, cy = aggregated.to_mercator(-3.70, 40.42)
    assert (x, y) in aggregated.tiles_in_extent((cx - 10, cy - 10, cx + 10, cy + 10), 13)
    assert len(aggregated.tiles_in_extent((cx - 10, cy - 10, cx + 10, cy + 10), 13)) <= 4
