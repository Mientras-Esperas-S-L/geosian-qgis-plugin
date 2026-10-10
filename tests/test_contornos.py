"""Contornos como el ``ContourLayer`` de la web, sin QGIS delante."""

import math

from geosian.core import contours


def _anillo(segmentos):
    """Los extremos de los segmentos, para ver dónde cae la isolínea."""
    return [p for s in segmentos for p in s]


def test_rejilla_suma_y_media():
    puntos = [(10, 10, 1), (20, 20, 1), (150, 10, 4)]
    rejilla = contours.grid(puntos, 100, "SUM")
    assert rejilla.value(0, 0) == 2 and rejilla.value(1, 0) == 4
    media = contours.grid(puntos, 100, "MEAN")
    assert media.value(0, 0) == 1 and media.value(1, 0) == 4


def test_la_isolinea_rodea_el_grupo_de_puntos():
    # Un grupo de 9 puntos en una celda de 100 m, en (500, 500).
    puntos = [(500 + dx, 500 + dy, 1) for dx in (10, 50, 90) for dy in (10, 50, 90)]
    rejilla = contours.grid(puntos, 100, "SUM")
    segmentos = contours.isolines(rejilla, 5)
    assert segmentos, "sin isolínea alrededor del grupo"
    centro = (550, 550)
    distancias = [math.dist(p, centro) for p in _anillo(segmentos)]
    # Interpolada entre el centro (9) y el vacío (0): a 4/9 de celda del centro.
    assert all(30 < d < 80 for d in distancias)


def test_un_umbral_por_encima_del_maximo_no_da_nada():
    rejilla = contours.grid([(0, 0, 1), (10, 10, 1)], 100, "SUM")
    assert contours.isolines(rejilla, 3) == []


def test_sin_puntos_no_hay_rejilla_ni_lineas():
    rejilla = contours.grid([], 100, "SUM")
    assert contours.isolines(rejilla, 1) == []


def test_la_isolinea_de_un_grupo_se_cierra():
    puntos = [(500 + dx, 500 + dy, 1) for dx in (10, 50, 90) for dy in (10, 50, 90)]
    puntos += [(620, 520, 6)]  # la celda de al lado, también por encima
    segmentos = contours.isolines(contours.grid(puntos, 100, "SUM"), 5)
    extremos = {}
    for s in segmentos:
        for p in s:
            clave = (round(p[0], 6), round(p[1], 6))
            extremos[clave] = extremos.get(clave, 0) + 1
    assert set(extremos.values()) == {2}


def test_teselas_para_cubrir_la_capa_con_celdas_de_media_celda():
    from geosian.core import aggregated

    # 200 m de celda: las del servidor (lado/96) deben quedar en torno a 100 m.
    z, teselas = aggregated.contour_tiles((-3.72, 40.40, -3.68, 40.43), 200)
    lado = 40075016.686 / 2 ** z / aggregated.CELDAS_DE_CALOR
    assert 50 <= lado <= 200
    assert teselas and len(teselas) <= aggregated.MAX_TESELAS
    # Una extensión enorme no pide cientos de teselas: baja el zoom.
    z2, muchas = aggregated.contour_tiles((-10, 35, 5, 44), 200)
    assert len(muchas) <= aggregated.MAX_TESELAS and z2 < z


def test_puntos_de_las_celdas_en_metros_con_su_peso():
    from geosian.core import aggregated

    celdas = [{"lng": 0.0, "lat": 0.0, "count": 4}, {"lng": 180.0, "lat": 0.0, "count": 1, "weight": 9.5},
              {"count": 3}]  # sin posición: fuera
    puntos = aggregated.cell_points(celdas, por_peso=False)
    assert abs(puntos[0][0]) < 1e-6 and abs(puntos[0][1]) < 1e-6 and puntos[0][2] == 4
    assert round(puntos[1][0]) == 20037508 and puntos[1][2] == 1
    assert len(puntos) == 2
    assert aggregated.cell_points(celdas, por_peso=True)[1][2] == 9.5
