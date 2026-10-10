"""Vistas por tramos (``graduated``) y por reglas (``rule_based``): cada elemento, del color
que le da la web.

Los colores esperados no se escriben a mano: salen de la función con la que la web pinta
las vistas (``buildFastViewColorFn``), ejecutada con node sobre los mismos casos
(``colores_web.mjs`` → ``colores_web.json``).
"""

import json
from pathlib import Path

import pytest

CASOS = json.loads((Path(__file__).parent / "colores_web.json").read_text(encoding="utf-8"))["casos"]
NUMERICOS = {"altura"}


def _capa(elementos):
    from qgis.core import QgsFeature, QgsVectorLayer

    nombres = sorted({k for e in elementos for k in e})
    campos = "&".join(f"field={n}:{'double' if n in NUMERICOS else 'string'}" for n in nombres)
    capa = QgsVectorLayer(f"Point?crs=EPSG:4326&{campos}", "p", "memory")
    nuevos = []
    for e in elementos:
        f = QgsFeature(capa.fields())
        valores = []
        for n in nombres:
            v = e.get(n)
            if n in NUMERICOS and v is not None:
                # Lo que hace QGIS con un texto en un campo numérico: o número, o nada.
                try:
                    v = float(v)
                except ValueError:
                    v = None
            valores.append(v)
        f.setAttributes(valores)
        nuevos.append(f)
    capa.dataProvider().addFeatures(nuevos)
    return capa


def _color_pintado(renderizador, elemento, contexto):
    from qgis.core import QgsSymbolLayer

    contexto.expressionContext().setFeature(elemento)
    simbolos = renderizador.symbolsForFeature(elemento, contexto)
    if not simbolos:
        return None  # no se pinta
    simbolo = simbolos[0]
    calculado = simbolo.symbolLayer(0).dataDefinedProperties().property(QgsSymbolLayer.PropertyFillColor)
    if calculado.isActive():
        from geosian.core import styles

        color, _ = calculado.valueAsColor(contexto.expressionContext(), simbolo.color())
        borde = simbolo.symbolLayer(0).dataDefinedProperties().property(QgsSymbolLayer.PropertyStrokeColor)
        assert borde.isActive()
        trazo, _ = borde.valueAsColor(contexto.expressionContext(), simbolo.color())
        assert tuple(trazo.getRgb()) == styles.stroke_of(tuple(color.getRgb()))
    else:
        color = simbolo.color()
    return list(color.getRgb())


@pytest.mark.parametrize("caso", CASOS, ids=[c["nombre"] for c in CASOS])
def test_cada_elemento_del_color_de_la_web(app, caso):
    from qgis.core import (
        QgsExpressionContext,
        QgsExpressionContextUtils,
        QgsRenderContext,
    )

    from geosian.core import symbology

    capa = _capa(caso["elementos"])
    resolver = symbology.field_resolver(capa.fields(), {})
    renderizador, _avisos = symbology.view_renderer(caso["config"], "points", {}, resolver)
    contexto = QgsRenderContext()
    contexto.setExpressionContext(QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(capa)))
    renderizador.startRender(contexto, capa.fields())
    try:
        pintados = [_color_pintado(renderizador, f, contexto) for f in capa.getFeatures()]
    finally:
        renderizador.stopRender(contexto)
    for elemento, esperado, pintado in zip(caso["elementos"], caso["colores"], pintados):
        assert pintado == esperado, f"{elemento}: web {esperado}, QGIS {pintado}"
