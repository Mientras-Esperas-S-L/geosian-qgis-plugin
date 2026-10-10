"""Lector mínimo de teselas vectoriales (MVT): capas y propiedades, sin geometría.

Para las celdas agregadas del servidor con ``geom=centroid``, que traen su posición en
las propiedades (``lng``, ``lat``) junto a ``count``, ``weight`` y ``density``. QGIS no
da a Python un decodificador cómodo, y estas teselas solo necesitan esto.
"""

import gzip
import struct


def _varint(datos, i):
    resultado = desplazamiento = 0
    while True:
        b = datos[i]
        i += 1
        resultado |= (b & 0x7F) << desplazamiento
        if not b & 0x80:
            return resultado, i
        desplazamiento += 7


def _campos(datos):
    """``(número, tipo, valor)`` de cada campo de un mensaje de protobuf."""
    i = 0
    while i < len(datos):
        clave, i = _varint(datos, i)
        numero, tipo = clave >> 3, clave & 7
        if tipo == 0:
            valor, i = _varint(datos, i)
        elif tipo == 1:
            valor, i = datos[i:i + 8], i + 8
        elif tipo == 2:
            largo, i = _varint(datos, i)
            valor, i = datos[i:i + largo], i + largo
        elif tipo == 5:
            valor, i = datos[i:i + 4], i + 4
        else:
            raise ValueError(f"Tipo de campo de protobuf no admitido: {tipo}")
        yield numero, tipo, valor


def _valor(datos):
    for numero, _, v in _campos(datos):
        if numero == 1:
            return v.decode("utf-8")
        if numero == 2:
            return struct.unpack("<f", v)[0]
        if numero == 3:
            return struct.unpack("<d", v)[0]
        if numero in (4, 5):
            return v
        if numero == 6:
            return (v >> 1) ^ -(v & 1)
        if numero == 7:
            return bool(v)
    return None


def _empaquetados(datos):
    i, salida = 0, []
    while i < len(datos):
        v, i = _varint(datos, i)
        salida.append(v)
    return salida


def decode(datos):
    """``{capa: [propiedades de cada objeto]}`` de una tesela MVT (también con gzip)."""
    datos = bytes(datos or b"")
    if datos[:2] == b"\x1f\x8b":
        datos = gzip.decompress(datos)
    capas = {}
    for numero, _, capa in _campos(datos):
        if numero != 3:
            continue
        nombre, claves, valores, objetos = "", [], [], []
        for n, _, v in _campos(capa):
            if n == 1:
                nombre = v.decode("utf-8")
            elif n == 2:
                objetos.append(v)
            elif n == 3:
                claves.append(v.decode("utf-8"))
            elif n == 4:
                valores.append(_valor(v))
        lista = []
        for objeto in objetos:
            etiquetas = []
            for n, _, v in _campos(objeto):
                if n == 2:
                    etiquetas = _empaquetados(v)
            lista.append({claves[etiquetas[k]]: valores[etiquetas[k + 1]]
                          for k in range(0, len(etiquetas) - 1, 2)})
        capas.setdefault(nombre, []).extend(lista)
    return capas
