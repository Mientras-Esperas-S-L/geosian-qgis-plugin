"""Servidor fijado al empaquetar.

Un paquete para probar en devel no debe poder conectarse a producción, ni al revés: el
técnico que lo prueba no tiene por qué saber qué dirección poner, y una conexión mal
puesta acaba escribiendo en los datos reales. `make package SERVIDOR=https://api.devel.greencitycontrol.com`
escribe la dirección aquí, en la copia que va al zip; en el código fuente se queda vacía y
el diálogo deja elegir servidor como siempre.
"""

# No tocar a mano: lo rellena `make package SERVIDOR=...` en la copia empaquetada.
SERVIDOR_FIJO = ""


def fijo():
    """La dirección del servidor fijado, o None si el paquete deja elegir."""
    return SERVIDOR_FIJO.rstrip("/") or None


def es_el_fijo(url):
    """Si ``url`` es la del servidor fijado. Sin servidor fijado, cualquiera vale."""
    servidor = fijo()
    return servidor is None or (url or "").rstrip("/") == servidor
