"""El motivo de un lote rechazado, como lo lee el técnico en la barra de QGIS.

Un cambio en bloque da el mismo error en muchos elementos. Si solo se nombra el
primero, el técnico lo arregla, guarda y le sale el siguiente.
"""

import json

from geosian.core.errors import ApiError
from geosian.provider.edicion import texto_de_error

OBLIGATORIO = "«plantacion_viaria» es obligatorio en Geosian al poner «zona» en «Viaria»"


def rechazo(cuerpo):
    return ApiError(400, "Bad Request", body=json.dumps(cuerpo).encode())


def test_el_mismo_error_en_varios_elementos_va_junto():
    errores = [{"op": "cambiar", "id": i, "campo": "plantacion_viaria", "error": OBLIGATORIO} for i in (7, 9, 12)]

    assert texto_de_error(rechazo({"errores": errores})) == f"elementos 7, 9, 12: {OBLIGATORIO}"


def test_muchos_elementos_se_resumen():
    errores = [{"op": "cambiar", "id": i, "error": OBLIGATORIO} for i in range(1, 101)]

    texto = texto_de_error(rechazo({"errores": errores, "total": 140}))

    assert texto == (
        f"elementos 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 y 90 más: {OBLIGATORIO}; 140 elementos con errores en total"
    )


def test_errores_distintos_por_separado():
    errores = [
        {"op": "cambiar", "id": 7, "error": OBLIGATORIO},
        {"op": "crear", "ref": "-1", "error": "Falta la geometría"},
        {"op": "cambiar", "id": 9, "error": OBLIGATORIO},
    ]

    assert texto_de_error(rechazo({"errores": errores})) == (
        f"elementos 7, 9: {OBLIGATORIO}; elemento nuevo: Falta la geometría"
    )


def test_uno_solo_como_antes():
    assert texto_de_error(rechazo({"errores": [{"id": 7, "error": "x"}]})) == "elemento 7: x"
    assert texto_de_error(rechazo({"errores": [{"error": "El lote está vacío"}]})) == "El lote está vacío"
