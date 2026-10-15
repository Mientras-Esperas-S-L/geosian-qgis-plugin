"""Fotos y archivos en las altas: se suben sueltos desde la ficha y el alta los engancha.

Con QGIS de verdad y el servidor falso, que responde como ``/geodata/adjuntos/`` y
``/geodata/confirmar/``.
"""

import base64
import json

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
from qgis.PyQt.QtGui import QColor, QImage

from geosian.core import adjuntos as A
from tests.fake_server import TODOS_LOS_PERMISOS
from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    lotes,
    servidor,
)


@pytest.fixture
def capa(servidor):  # noqa: F811
    return abrir(servidor)


def foto(tmp_path, nombre="foto.png", ancho=40, alto=30):
    imagen = QImage(ancho, alto, QImage.Format.Format_RGB32)
    imagen.fill(QColor(200, 10, 10))
    ruta = str(tmp_path / nombre)
    assert imagen.save(ruta)
    return ruta


def subir(servidor, campo, nombre="foto.png", contenido=b"x"):  # noqa: F811
    estado, cuerpo = servidor.estado.subir_adjunto({
        "layer_id": 11, "geometry_type": "points", "campo": campo, "nombre": nombre,
        "datos": base64.b64encode(contenido).decode(),
    })
    assert estado == 201, cuerpo
    return cuerpo


def nuevo(capa, **valores):
    if not capa.isEditable():
        assert capa.startEditing()
    feature = QgsFeature(capa.fields())
    for nombre, valor in valores.items():
        feature[nombre] = valor
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-3.69, 40.41)))
    assert capa.addFeature(feature)
    return feature


def entrada(subida, ruta=""):
    return {
        "campo": subida["campo"], "adjunto": subida["adjunto"], "nombre": subida["nombre"],
        "tipo": subida["tipo"], "ruta": ruta,
    }


class TestElAlta:
    def test_lleva_las_referencias_en_su_campo_y_geosian_se_queda_los_adjuntos(self, capa, servidor):  # noqa: F811
        una = subir(servidor, "pictures", "a.jpg", b"AAA")
        otra = subir(servidor, "files", "informe.pdf", b"%PDF")
        nuevo(capa, codigo="N-1", adjuntos_nuevos=A.escribir([entrada(una), entrada(otra)]))

        assert capa.commitChanges(), capa.commitErrors()

        [alta] = lotes(servidor)[-1]["crear"]
        assert alta["attributes"]["pictures"] == [{"adjunto": una["adjunto"]}]
        assert alta["attributes"]["files"] == [{"adjunto": otra["adjunto"]}]
        assert "adjuntos_nuevos" not in alta["attributes"]
        assert servidor.estado.adjuntos_de[2001] == {
            "pictures": [("a.jpg", b"AAA")], "files": [("informe.pdf", b"%PDF")],
        }
        # Ya son del elemento en Geosian: el campo de las nuevas queda vacío.
        assert capa.getFeature(2001)["adjuntos_nuevos"] in (None, "") or capa.getFeature(2001)[
            "adjuntos_nuevos"
        ].isNull()

    def test_si_el_adjunto_ya_no_esta_el_alta_sigue_pendiente(self, capa, servidor):  # noqa: F811
        una = subir(servidor, "pictures")
        servidor.estado.adjuntos.clear()
        nuevo(capa, codigo="N-2", adjuntos_nuevos=A.escribir([entrada(una)]))

        assert not capa.commitChanges()
        assert "ya no está" in " ".join(capa.commitErrors())
        assert capa.isEditable()
        assert len(capa.editBuffer().addedFeatures()) == 1

    def test_a_un_elemento_ya_guardado_no_se_le_anaden(self, capa, servidor):  # noqa: F811
        una = subir(servidor, "pictures")
        assert capa.startEditing()
        assert capa.changeAttributeValue(
            1001, capa.fields().indexOf("adjuntos_nuevos"), A.escribir([entrada(una)])
        )

        assert not capa.commitChanges()
        assert "desde la web" in " ".join(capa.commitErrors())
        assert not lotes(servidor)

    def test_el_campo_no_viene_del_servidor(self, capa):
        assert all(f["adjuntos_nuevos"] in (None, "") or f["adjuntos_nuevos"].isNull() for f in capa.getFeatures())


class TestLaFicha:
    def ficha_nueva(self, capa):
        from qgis.gui import QgsAttributeEditorContext, QgsAttributeForm

        from geosian.gui import formulario, media_widget
        from tests.test_gui import _herramientas_falsas

        media_widget.register_media_widget()
        formulario.aplicar_esquema(capa)
        if not capa.isEditable():
            assert capa.startEditing()
        contexto = QgsAttributeEditorContext()
        contexto.setVectorLayerTools(_herramientas_falsas())
        feature = QgsFeature(capa.fields())
        # El esquema de prueba pide el código en un alta.
        feature["codigo"] = "N-9"
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-3.69, 40.41)))
        ficha = QgsAttributeForm(capa, feature, contexto)
        ficha.setMode(QgsAttributeEditorContext.Mode.AddFeatureMode)
        panel = ficha.findChildren(media_widget.MediaPanel)[0]
        panel.cargar()
        return ficha, panel

    def test_anadir_una_foto_la_sube_reducida_y_la_apunta(self, capa, servidor, tmp_path):  # noqa: F811
        ficha, panel = self.ficha_nueva(capa)
        assert panel.botones.isVisibleTo(panel)

        panel.añadir("pictures", "Fotos", "foto", rutas=[foto(tmp_path, ancho=3200, alto=1000)])

        [subida] = [d for r, d in servidor.peticiones if r == "/api/v1/geodata/adjuntos/"]
        assert subida["campo"] == "pictures" and subida["nombre"] == "foto.jpg"
        [(ref, guardado)] = servidor.estado.adjuntos.items()
        reducida = QImage.fromData(guardado["contenido"])
        assert (reducida.width(), reducida.height()) == (1600, 500)
        assert [e["adjunto"] for e in panel.nuevos] == [ref]
        assert panel.fotos.count() == 1

        # Al guardar la ficha, el elemento lleva la referencia y el alta la manda.
        assert ficha.save()
        assert capa.commitChanges(), capa.commitErrors()
        assert lotes(servidor)[-1]["crear"][0]["attributes"]["pictures"] == [{"adjunto": ref}]

    def test_quitar_lo_anadido(self, capa, servidor, tmp_path):  # noqa: F811
        _, panel = self.ficha_nueva(capa)
        panel.añadir("pictures", "Fotos", "foto", rutas=[foto(tmp_path, "a.png"), foto(tmp_path, "b.png")])
        panel.fotos.item(0).setSelected(True)

        panel.quitar_seleccion()

        assert [e["nombre"] for e in panel.nuevos] == ["b.png"]

    def test_un_rechazo_de_geosian_se_ve_y_no_se_apunta(self, capa, servidor, tmp_path):  # noqa: F811
        _, panel = self.ficha_nueva(capa)
        malo = tmp_path / "virus.exe"
        malo.write_bytes(b"MZ")

        panel.añadir("files", "Archivos", "fichero", rutas=[str(malo)])

        assert panel.nuevos == []
        assert "no está permitido" in panel.estado.text()

    def test_como_mucho_quince_por_campo(self, capa, servidor, tmp_path):  # noqa: F811
        _, panel = self.ficha_nueva(capa)

        panel.añadir("pictures", "Fotos", "foto", rutas=[foto(tmp_path)] * 16)

        assert panel.nuevos == []
        assert not servidor.estado.adjuntos

    def test_sin_permiso_de_alta_no_hay_botones(self, servidor):  # noqa: F811
        servidor.estado.permisos[11] = {**TODOS_LOS_PERMISOS, "can_create": False}
        capa = abrir(servidor)
        _, panel = self.ficha_nueva(capa)

        assert not panel.botones.isVisibleTo(panel)


def test_una_foto_pequena_va_tal_cual(tmp_path):
    from geosian.gui.media_widget import preparar_foto

    ruta = foto(tmp_path)
    contenido, nombre = preparar_foto(ruta)

    assert nombre == "foto.png"
    with open(ruta, "rb") as original:
        assert contenido == original.read()


def test_las_entradas_se_leen_y_escriben(tmp_path):
    entradas = [{"campo": "pictures", "adjunto": "r1", "nombre": "a", "tipo": "foto", "ruta": ""}]

    assert A.leer(A.escribir(entradas)) == entradas
    assert A.leer(None) == [] and A.leer("no es json") == [] and A.escribir([]) is None
    assert A.para_el_alta(entradas) == {"pictures": [{"adjunto": "r1"}]}
    assert json.loads(A.escribir(entradas))[0]["adjunto"] == "r1"
