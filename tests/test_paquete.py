"""El zip que se instala en QGIS (``make package``): lo que lleva y lo que no."""

import configparser
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

OBLIGATORIOS = [
    "name", "qgisMinimumVersion", "description", "about", "version", "author", "email",
    "repository", "tracker", "homepage", "changelog", "icon",
]


@pytest.fixture(scope="module")
def paquete(tmp_path_factory):
    # El zip no depende de la versión de QGIS: donde no hay con qué hacerlo (el
    # contenedor de QGIS 3.34), no se prueba.
    if not all(shutil.which(h) for h in ("make", "git", "zip")):
        pytest.skip("sin make, git o zip")
    salida = tmp_path_factory.mktemp("paquete")
    subprocess.run(["make", "-s", "package", f"BUILD={salida}"], cwd=RAIZ, check=True,
                   capture_output=True)
    [zip_] = salida.glob("geosian-*.zip")
    with zipfile.ZipFile(zip_) as z:
        yield z


def test_lleva_lo_que_pide_el_repositorio_de_complementos(paquete):
    nombres = paquete.namelist()
    assert all(n.startswith("geosian/") for n in nombres)
    assert "geosian/__init__.py" in nombres
    assert "geosian/LICENSE" in nombres
    meta = configparser.ConfigParser()
    meta.read_string(paquete.read("geosian/metadata.txt").decode("utf-8"))
    general = meta["general"]
    for clave in OBLIGATORIOS:
        assert general.get(clave, "").strip(), clave
    assert f"geosian/{general['icon']}" in nombres
    # El primer apartado del registro de cambios es la versión que se publica.
    assert general["changelog"].strip().split()[0] == general["version"]


def test_no_lleva_pruebas_ni_caches(paquete):
    for nombre in paquete.namelist():
        assert not re.search(r"__pycache__|\.py[co]$|\.ruff_cache|\.pytest_cache|/tests?/", nombre), nombre


def test_la_descripcion_no_promete_escritura(paquete):
    """Fase 1: solo lectura. La escritura llega en la fase 2."""
    meta = configparser.ConfigParser()
    meta.read_string(paquete.read("geosian/metadata.txt").decode("utf-8"))
    texto = (meta["general"]["description"] + meta["general"]["about"]).lower()
    assert "escrib" not in texto
