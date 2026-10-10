"""Un atributo definido dos veces en el esquema, en ramas distintas del formulario.

En el arbolado de Cáceres, «Especie» (``ref_especie``) está en la rama de árboles con la
lista de especies de árbol y en la de palmeras con la de palmeras: la web enseña la que toca
según el porte. Es un solo dato. QGIS creaba ``ref_especie`` y un ``ref_especie_2`` que no
recibía nada, y la lista de palmeras pisaba la de árboles en ``ref_especie``: un fresno salía
«(FRAXINUS ANGUSTIFOLIA)», el valor que no está en la lista.
"""

import pytest

pytest.importorskip("qgis.core")


ESQUEMA = {"attributes": [
    {"name": "porte_arboreo", "type": "select", "allowed_values": ["arbol", "palmera"]},
    {"type": "section_decision", "name": "section_decision_1", "contents": [
        {"type": "section", "name": "taxonomia_arb", "contents": [
            {"name": "ref_especie", "type": "autocomplete", "title": "Especie",
             "allowed_values": ["ACER NEGUNDO", "FRAXINUS ANGUSTIFOLIA"]}]}]},
    {"type": "section_decision", "name": "section_decision_2", "contents": [
        {"type": "section", "name": "taxonomia_palm", "contents": [
            {"name": "ref_especie", "type": "autocomplete", "title": "Especie",
             "allowed_values": ["PHOENIX CANARIENSIS", "ACER NEGUNDO"]}]}]},
]}


def test_un_solo_campo_con_la_union_de_las_listas(app):
    from qgis.core import QgsVectorLayer

    from geosian.core import lad

    campos, mapa = lad.build_fields(ESQUEMA)
    nombres = [c.name() for c in campos]
    assert nombres.count("ref_especie") == 1
    assert "ref_especie_2" not in nombres

    capa = QgsVectorLayer("Point?crs=EPSG:4326", "a", "memory")
    capa.dataProvider().addAttributes(list(campos))
    capa.updateFields()
    lad.apply_editor_config(capa, ESQUEMA)
    idx = capa.fields().indexOf("ref_especie")
    valores = [next(iter(v)) for v in capa.editorWidgetSetup(idx).config()["map"]]
    # Las de las dos ramas, en orden y sin repetir.
    assert valores == ["ACER NEGUNDO", "FRAXINUS ANGUSTIFOLIA", "PHOENIX CANARIENSIS"]
    assert mapa["ref_especie"]["allowed_values"] == valores
