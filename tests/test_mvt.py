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
