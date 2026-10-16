"""Las fotos y los ficheros de un elemento nuevo, a la espera de su alta.

Geosian no los recibe dentro del lote: el complemento sube cada uno suelto
(``POST /geodata/adjuntos/``) al añadirlo en la ficha y guarda la referencia que le
dan. Las referencias de un elemento viajan en su campo ``adjuntos_nuevos``
(``schema.CAMPO_ADJUNTOS``) como texto JSON, así van con el elemento en lo pendiente
de QGIS (deshacer, copiar). Al confirmar, el alta las lleva en su campo del LAD como
``[{"adjunto": ref}]``. Si no se confirma, en Geosian caducan solas a las 24 horas.

Cada entrada: ``{"campo", "adjunto", "nombre", "tipo", "ruta"}``, con ``tipo``
``foto`` o ``fichero`` y ``ruta`` la copia local, para enseñar la miniatura.
"""

import json

# Como la web: hasta 15 por campo.
MAXIMO_POR_CAMPO = 15


def leer(valor):
    """Las entradas guardadas en el campo; lista vacía si no hay o no se entiende."""
    if valor is None or (hasattr(valor, "isNull") and valor.isNull()) or valor == "":
        return []
    try:
        lista = json.loads(valor) if isinstance(valor, str) else valor
    except ValueError:
        return []
    if not isinstance(lista, list):
        return []
    return [e for e in lista if isinstance(e, dict) and e.get("campo") and e.get("adjunto")]


def escribir(entradas):
    """Lo que se guarda en el campo: el JSON de las entradas, o nada si no hay."""
    return json.dumps(list(entradas), ensure_ascii=False) if entradas else None


def para_el_alta(entradas):
    """``{campo: [{"adjunto": ref}, ...]}``, en el orden en que se añadieron."""
    salida = {}
    for entrada in entradas:
        salida.setdefault(entrada["campo"], []).append({"adjunto": entrada["adjunto"]})
    return salida
