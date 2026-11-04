"""La lógica de las condiciones combinadas (core/filtro_arbol.py), sin QGIS.

Es la misma que la del constructor de la web (src/utils/filtroArbol.js): estas pruebas
repiten sus casos para que los dos lados no se separen.
"""

from geosian.core import filtro_arbol as F


def test_tipos_y_operadores():
    assert F.tipo_de_campo({"type": "select", "allowed_values": ["A"]}) == "lista"
    assert F.tipo_de_campo({"type": "checkbox", "allowed_values": ["A", "B"]}) == "casillas"
    assert F.tipo_de_campo({"type": "number"}) == "numero"
    assert F.tipo_de_campo({"type": "calendar"}) == "fecha"
    assert F.tipo_de_campo({"type": "text"}) == "texto"
    assert "gt" in [op for op, _ in F.operadores_de("numero")]
    assert "gt" not in [op for op, _ in F.operadores_de("lista")]


def test_cambiar_de_operador_conserva_lo_escrito():
    assert F.convertir_valor("Pino", "contiene", "es_uno_de") == ["Pino"]
    assert F.convertir_valor(["Pino", "Encina"], "es_uno_de", "contiene") == "Pino"
    assert F.convertir_valor("5", "gt", "entre") == {"desde": "5", "hasta": ""}
    assert F.convertir_valor({"desde": "5", "hasta": "9"}, "entre", "gte") == "5"
    assert F.convertir_valor("5", "gt", "vacio") is None


def test_limpiar_quita_lo_que_esta_a_medias():
    arbol = {"todas": True, "condiciones": [
        {"campo": "especie", "op": "es_uno_de", "valor": [" Pino ", ""]},
        {"campo": "altura", "op": "gt", "valor": ""},
        {"todas": False, "condiciones": [{"campo": "estado", "op": "es_uno_de", "valor": []}]},
        {"partes": "parte_trabajo", "tiene": False, "periodo": {"ultimos_dias": "30"}, "condiciones": []},
    ]}
    assert F.limpiar_arbol(arbol) == {"todas": True, "condiciones": [
        {"campo": "especie", "op": "es_uno_de", "valor": ["Pino"]},
        {"partes": "parte_trabajo", "tiene": False, "todas": True, "ultimo": False, "condiciones": [],
         "periodo": {"ultimos_dias": 30}},
    ]}
    assert F.limpiar_arbol({"todas": True, "condiciones": [{"campo": "a", "op": "gt", "valor": ""}]}) is None


def test_la_frase_dice_lo_mismo_que_en_la_web():
    arbol = {"todas": True, "condiciones": [
        {"campo": "zona", "op": "es_uno_de", "valor": ["Viaria"]},
        {"todas": False, "condiciones": [
            {"campo": "marcado", "op": "tiene_alguno", "valor": ["Riesgo", "Plaga"]},
            {"campo": "altura", "op": "gt", "valor": "10"},
        ]},
        {"partes": "parte_trabajo", "tiene": False, "periodo": {"ultimos_dias": 30},
         "condiciones": [{"campo": "riego", "op": "no_vacio"}]},
    ]}
    titulos = {"zona": "Zona", "marcado": "Marcado como", "altura": "Altura", "riego": "Riego"}
    frase = F.frase_del_arbol(arbol, lambda n, p=None: titulos.get(n, n), lambda n: "Parte de trabajo")
    assert frase == (
        "Zona es uno de Viaria y (Marcado como tiene alguno de Riesgo, Plaga o Altura mayor que 10) y "
        "sin ningún parte de Parte de trabajo en los últimos 30 días: Riego no está vacío"
    )
    assert F.frase_del_arbol(None) == "Todos los elementos"
