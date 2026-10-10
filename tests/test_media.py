"""Fotos y adjuntos tal y como los da la API, sin QGIS delante."""

import base64

from geosian.core import media

JPEG = b"\xff\xd8\xff\xe0 foto de prueba"


def test_foto_incrustada_del_detalle_de_un_elemento():
    # /geodata/<id>/ las manda en base64, con su id.
    detalle = {
        "pictures": [
            {
                "id": 7,
                "data": "data:image/jpg;base64," + base64.b64encode(JPEG).decode(),
                "created_at": "2026-05-02T09:00:00+02:00",
                "main_image": True,
                "field_name": "pictures",
            }
        ],
        "files": [],
    }

    [foto] = media.items_from(detalle, image_url="/api/v1/geodata/image/{id}/")

    assert foto.kind == "image"
    assert foto.data == JPEG
    assert foto.main
    assert foto.url == "/api/v1/geodata/image/7/"


def test_foto_por_enlace_de_un_parte():
    # El listado de partes las manda como enlace, sin el contenido.
    parte = {"pictures": [{"id": 9, "url": "/api/v1/additional-information/image/9/", "main_image": False}]}

    [foto] = media.items_from(parte)

    assert foto.data is None
    assert foto.url == "/api/v1/additional-information/image/9/"


def test_ficheros_con_su_nombre_y_su_enlace():
    detalle = {"pictures": [], "files": [{"id": 3, "name": "informe.pdf", "field_name": "files"}]}

    [fichero] = media.items_from(detalle, file_url="/api/v1/geodata/file/{id}/")

    assert fichero.kind == "file"
    assert fichero.name == "informe.pdf"
    assert fichero.url == "/api/v1/geodata/file/3/"


def test_la_portada_va_primero_y_lo_roto_se_ignora():
    detalle = {
        "pictures": [
            {"id": 1, "url": "/a/1/"},
            {"id": 2, "url": "/a/2/", "main_image": True},
            {"id": 3, "data": "data:image/jpg;base64,@@no-es-base64@@"},
            "basura",
        ]
    }

    assert [f.id for f in media.items_from(detalle)] == [2, 1]


def test_sin_medios():
    assert media.items_from(None) == []
    assert media.items_from({"pictures": None, "files": None}) == []


def test_foto_por_enlace_con_miniatura():
    # El detalle con embed_images=false: enlace a la foto y a su miniatura.
    detalle = {"pictures": [{"id": 7, "url": "/api/v1/geodata/image/7/",
                             "thumbnail_url": "/api/v1/geodata/image/7/?as_thumbnail=1",
                             "main_image": True}]}

    [foto] = media.items_from(detalle)

    assert foto.data is None
    assert foto.url == "/api/v1/geodata/image/7/"
    assert foto.thumb_url == "/api/v1/geodata/image/7/?as_thumbnail=1"


def test_las_fotos_de_la_api_sin_miniatura_declarada_la_piden():
    # Las de los partes traen solo «url»; su vista sirve la miniatura igual.
    [foto] = media.items_from({"pictures": [{"id": 9, "url": "/api/v1/additional-information/image/9/"}]})
    assert foto.thumb_url == "/api/v1/additional-information/image/9/?as_thumbnail=1"


def test_una_foto_que_no_es_de_la_api_no_tiene_miniatura():
    [foto] = media.items_from({"pictures": [{"id": 9, "url": "/a/9/"}]})
    assert foto.thumb_url is None
