"""Un lote grande Geosian lo aplica en segundo plano (202), y sigue siendo todo o nada.

El cliente pregunta por la tarea hasta que acaba y devuelve o lanza lo mismo que con el
lote síncrono. En QGIS, la confirmación espera sin congelar la ventana y avisa.
"""

import json

import pytest

from geosian.core import client as C
from geosian.core.client import GeosianClient
from geosian.core.errors import ApiError, ConflictError, LoteIncierto, NetworkError
from geosian.core.http import Response, Transport


def respuesta(datos, status=200):
    return Response(status, json.dumps(datos).encode("utf-8"))


class TransporteEnCola(Transport):
    """Al POST, 202; a cada pregunta por la tarea, la siguiente de ``estados``."""

    def __init__(self, estados):
        self.estados = list(estados)
        self.urls = []

    def request(self, method, url, headers=None, body=None, timeout=30):
        self.urls.append((method, url))
        if method == "POST":
            return respuesta({"task_id": "t1", "status_url": "/api/v1/tasks/t1/status/", "total": 500}, 202)
        siguiente = self.estados.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        if isinstance(siguiente, tuple):
            return respuesta(siguiente[1], siguiente[0])
        return respuesta(siguiente)


def en_curso():
    return {"status": "STARTED", "result_data": None, "error_message": ""}


def acabada(estado, cuerpo):
    return {
        "status": "SUCCESS" if estado == 200 else "FAILURE",
        "result_data": {"estado": estado, "cuerpo": cuerpo},
        "error_message": "",
    }


def confirmar(transporte, **kwargs):
    cliente = GeosianClient("https://geo.ejemplo", transport=transporte, token="t")
    return cliente.confirmar(11, "points", cambiar=[{"id": 1}], esperar=lambda s: None, **kwargs)


def test_espera_a_la_tarea_y_devuelve_su_respuesta():
    hecho = {"creados": [], "cambiados": [{"id": 1, "updated_at": "x"}], "retirados": []}
    transporte = TransporteEnCola([en_curso(), en_curso(), acabada(200, hecho)])
    avisos = []

    assert confirmar(transporte, al_encolar=avisos.append) == hecho

    assert avisos == [500]
    assert [u for m, u in transporte.urls if m == "GET"] == ["https://geo.ejemplo/api/v1/tasks/t1/status/"] * 3


def test_un_409_de_la_tarea_es_el_mismo_conflicto():
    choques = {"conflictos": [{"op": "cambiar", "id": 1}]}
    transporte = TransporteEnCola([acabada(409, choques)])

    with pytest.raises(ConflictError) as exc:
        confirmar(transporte)

    assert json.loads(exc.value.body) == choques


def test_un_corte_al_preguntar_no_da_el_lote_por_fallido():
    hecho = {"creados": [], "cambiados": [], "retirados": []}
    transporte = TransporteEnCola([NetworkError("sin red"), acabada(200, hecho)])

    assert confirmar(transporte) == hecho


def test_un_fallo_sin_respuesta_es_un_error_de_la_api():
    transporte = TransporteEnCola([{"status": "FAILURE", "result_data": None, "error_message": "worker caído"}])

    with pytest.raises(ApiError) as exc:
        confirmar(transporte)

    assert exc.value.status == 500
    assert "worker caído" in str(exc.value)


def test_si_no_acaba_a_tiempo_no_se_sabe_si_entro(monkeypatch):
    monkeypatch.setattr(C, "ESPERA_DE_LOTE", -1)
    transporte = TransporteEnCola([en_curso()])

    with pytest.raises(LoteIncierto, match="No se sabe si Geosian ha guardado"):
        confirmar(transporte)


def test_un_502_al_preguntar_es_pasajero():
    """Un despliegue recarga el servidor y da 502 unos segundos: el lote sigue."""
    hecho = {"creados": [], "cambiados": [], "retirados": []}
    transporte = TransporteEnCola([(502, {"detail": "Bad Gateway"}), (503, {}), acabada(200, hecho)])

    assert confirmar(transporte) == hecho


def test_sin_credencial_al_preguntar_no_se_sabe_si_entro():
    transporte = TransporteEnCola([(401, {"detail": "Credenciales no válidas"})])

    with pytest.raises(LoteIncierto, match="Vuelve a guardar sin tocar nada"):
        confirmar(transporte)


def test_un_corte_al_enviar_no_se_sabe_si_entro():
    class SeCorta(TransporteEnCola):
        def request(self, method, url, headers=None, body=None, timeout=30):
            raise NetworkError("conexión cerrada")

    with pytest.raises(LoteIncierto):
        confirmar(SeCorta([]))


def test_en_cola_espera_mas_que_arrancado(monkeypatch):
    """El plazo de 27 minutos cuenta desde que arranca, no desde que se envía."""
    reloj = [0.0]
    monkeypatch.setattr(C.time, "monotonic", lambda: reloj[0])
    hecho = {"creados": [], "cambiados": [], "retirados": []}
    pendiente = {"status": "PENDING", "result_data": None, "error_message": ""}

    def esperar(segundos):
        reloj[0] += 20 * 60

    transporte = TransporteEnCola([pendiente, en_curso(), en_curso(), acabada(200, hecho)])
    cliente = GeosianClient("https://geo.ejemplo", transport=transporte, token="t")

    assert cliente.confirmar(11, "points", cambiar=[{"id": 1}], esperar=esperar) == hecho
