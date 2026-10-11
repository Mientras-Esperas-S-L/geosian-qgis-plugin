"""Lo que la web no deja hacer lo para el servidor en el lote (``reglas_de_la_web``).

El complemento no repite esas reglas: muestra el error de Geosian y lo deja todo
pendiente. Aquí, contra el servidor falso, que las aplica como el de verdad.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    indice,
    lotes,
    servidor,
)


@pytest.fixture
def capa(servidor):  # noqa: F811
    return abrir(servidor)


def test_un_campo_oculto_en_la_web_no_se_cambia(capa, servidor):  # noqa: F811
    editar(capa, 1001, codigo_migracion="OTRO", altura=1.0)

    assert not capa.commitChanges()

    assert capa.isEditable()
    assert 1001 in capa.editBuffer().changedAttributeValues()
    assert any("codigo_migracion" in e and "solo lectura" in e for e in capa.commitErrors())
    assert elemento(servidor, 1001)["altura"] != 1.0
