"""La ficha de una capa de Geosian a partir de su esquema.

La usan el panel, al añadir la capa, y el tiempo real, cuando el esquema cambia
en GCC y hay que rehacerla sin quitar la capa.
"""

from qgis.core import QgsProject

from ..core import lad
from ..provider.uri import parse_uri
from . import media_widget


def aplicar_esquema(capa):
    """Tipos de campo, pestañas y panel de fotos según el esquema de la capa."""
    esquema = getattr(capa.dataProvider(), "schema", None)
    if not esquema:
        return
    lad.apply_editor_config(capa, esquema)
    lad.apply_form(capa, esquema)
    if media_widget.is_available():
        lad.add_media_tab(capa, esquema, media_widget.WIDGET_TYPE)


def rehacer(capa):
    """Vuelve a montar la ficha, con la pestaña de partes si la capa la tenía.

    ``apply_form`` empieza de cero, así que la pestaña de partes se monta otra vez
    con las relaciones que ya hay en el proyecto y los tipos del esquema nuevo.
    """
    aplicar_esquema(capa)
    if not capa.isSpatial():
        return
    tipos = {
        info.get("name"): info
        for info in (getattr(capa.dataProvider(), "schema", None) or {}).get(
            "additional_information"
        ) or []
        if isinstance(info, dict)
    }
    relaciones = []
    for relacion in QgsProject.instance().relationManager().referencedRelations(capa):
        tabla = relacion.referencingLayer()
        if tabla is None or tabla.providerType() != "geosian":
            continue
        try:
            info = tipos.get(parse_uri(tabla.source()).info_name)
        except ValueError:
            continue
        if info is not None:
            relaciones.append((relacion, info))
    if relaciones:
        lad.add_relations_tab(capa, relaciones)
