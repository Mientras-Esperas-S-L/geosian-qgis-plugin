"""Datos que no casan con el tipo de su campo, como los importados antes del LAD.

En devel, la mitad del arbolado de Talher tiene "0-5 m" en un campo de número, y hay
números guardados como texto ("430"), textos vacíos y listas vacías. Volver a poner
lo que ya había no es un cambio, y un número que no lo es para la confirmación con
el motivo: antes lanzaba dentro de ``beforeCommitChanges`` y QGIS se cerraba.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsFeature

from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    indice,
    lotes,
    servidor,
)


def con(servidor, fid, **valores):  # noqa: F811
    propiedades = next(e for e in servidor.estado.elementos if e["properties"]["id"] == fid)["properties"]
    propiedades.update(valores)


def valor(capa, fid, nombre):
    return capa.getFeature(fid)[nombre]


def reescribir(capa, nombre):
    """Lo que hace la calculadora de campos con "campo" = "campo"."""
    if not capa.isEditable():
        assert capa.startEditing()
    i = indice(capa, nombre)
    campo = capa.fields().at(i)
    for elemento_qgis in capa.getFeatures():
        nuevo = elemento_qgis.attribute(i)
        convertido = campo.convertCompatible(nuevo)
        nuevo = convertido[-1] if isinstance(convertido, tuple) else convertido
        assert capa.changeAttributeValue(elemento_qgis.id(), i, nuevo)


def test_un_numero_guardado_como_texto_se_lee_como_numero(servidor):  # noqa: F811
    con(servidor, 1001, altura="430")
    con(servidor, 1002, altura="")
    capa = abrir(servidor)

    assert valor(capa, 1001, "altura") == 430.0
    assert valor(capa, 1002, "altura") is None or valor(capa, 1002, "altura").isNull()


def test_reescribir_lo_que_habia_no_manda_nada(servidor):  # noqa: F811
    con(servidor, 1001, altura="430", codigo=15, operacion=[])
    con(servidor, 1002, altura="")
    capa = abrir(servidor)

    for nombre in ("altura", "codigo", "operacion"):
        reescribir(capa, nombre)

    assert capa.commitChanges(), capa.commitErrors()
    assert lotes(servidor) == []


def test_un_texto_en_un_campo_de_numero_se_conserva_si_no_se_toca(servidor):  # noqa: F811
    con(servidor, 1001, altura="0-5 m")
    capa = abrir(servidor)
    assert valor(capa, 1001, "altura") == "0-5 m"

    assert capa.startEditing()
    assert capa.changeAttributeValue(1001, indice(capa, "altura"), "0-5 m")
    editar(capa, 1001, observaciones="Revisado")

    assert capa.commitChanges(), capa.commitErrors()
    assert elemento(servidor, 1001)["altura"] == "0-5 m"
    assert elemento(servidor, 1001)["observaciones"] == "Revisado"


def test_un_texto_nuevo_en_un_campo_de_numero_no_entra_y_qgis_sigue(servidor):  # noqa: F811
    con(servidor, 1001, altura="0-5 m")
    capa = abrir(servidor)

    editar(capa, 1001, altura="5-10 m")

    assert not capa.commitChanges()
    assert lotes(servidor) == []
    assert any("5-10 m" in e and "número" in e for e in capa.commitErrors())


def test_pegar_un_elemento_con_texto_en_un_numero_no_entra(servidor):  # noqa: F811
    con(servidor, 1001, altura="0-5 m")
    capa = abrir(servidor)
    copia = QgsFeature(capa.getFeature(1001))

    assert capa.startEditing()
    assert capa.addFeature(copia)

    assert not capa.commitChanges()
    assert lotes(servidor) == []
    assert any("0-5 m" in e for e in capa.commitErrors())


def test_un_fallo_al_preparar_el_lote_no_cierra_qgis(servidor, monkeypatch):  # noqa: F811
    capa = abrir(servidor)
    proveedor = capa.dataProvider()

    def roto(buffer):
        raise RuntimeError("algo imprevisto")

    monkeypatch.setattr(proveedor, "_lote_de", roto)
    editar(capa, 1001, observaciones="Revisado")

    assert not capa.commitChanges()
    assert lotes(servidor) == []
    assert any("algo imprevisto" in e for e in capa.commitErrors())
