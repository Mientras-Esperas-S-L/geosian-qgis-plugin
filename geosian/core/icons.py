"""Iconos de las vistas de GCC, sin QGIS delante.

El editor de vistas guarda el icono como ``{"lib": "fa", "name": "FaTree"}``: un
componente de ``react-icons``. Cada librería del paquete es un módulo con una
función por icono que devuelve su dibujo como un árbol SVG en JSON::

    export function FaTree (props) {
      return GenIcon({"tag":"svg","attr":{"viewBox":"0 0 384 512"},"child":[...]})(props);
    };

Aquí se saca ese árbol y se convierte en un SVG que QGIS pinta como marcador,
con el color como parámetro (``param(fill)``) para teñirlo por elemento igual
que la web, que lo usa como máscara.

La versión es la del frontal: si cambia allí, hay que cambiarla aquí para que
los dibujos coincidan.
"""

import json
import re

REACT_ICONS_VERSION = "5.5.0"

LIBRARIES = {
    "ai", "bi", "bs", "cg", "ci", "di", "fa", "fa6", "fc", "fi", "gi", "go", "gr",
    "hi", "hi2", "im", "io", "io5", "lia", "lu", "md", "pi", "ri", "rx", "si", "sl",
    "tb", "tfi", "ti", "vsc", "wi",
}

_NOMBRE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def library_url(lib):
    """Dónde está publicada una librería del paquete, o ``None`` si no existe."""
    if lib not in LIBRARIES:
        return None
    return f"https://cdn.jsdelivr.net/npm/react-icons@{REACT_ICONS_VERSION}/{lib}/index.mjs"


def extract_tree(modulo, nombre):
    """El árbol SVG de un icono dentro del texto de su librería, o ``None``."""
    if not _NOMBRE.match(str(nombre or "")):
        return None
    patron = re.compile(
        r"export function " + re.escape(nombre) + r" \(props\) \{\s*return GenIcon\((.*?)\)\(props\);",
        re.DOTALL,
    )
    encontrado = patron.search(modulo or "")
    if not encontrado:
        return None
    try:
        return json.loads(encontrado.group(1))
    except ValueError:
        return None


def tree_to_svg(arbol, tamaño=128):
    """SVG con el color como parámetro de QGIS.

    El color del icono es ``currentColor`` en ``react-icons`` y la web lo pinta
    como máscara. Aquí ``currentColor`` pasa a ``param(fill)``, y el ``svg``
    raíz rellena con ``param(fill)`` si no dice nada, que es el caso de la
    mayoría de iconos sólidos.
    """
    raiz = dict(arbol or {})
    atributos = dict(raiz.get("attr") or {})
    atributos.setdefault("fill", "currentColor")
    atributos["width"] = str(tamaño)
    atributos["height"] = str(tamaño)
    atributos["xmlns"] = "http://www.w3.org/2000/svg"
    raiz["attr"] = atributos
    return _nodo(raiz)


def _nodo(nodo):
    etiqueta = str(nodo.get("tag") or "g")
    partes = [etiqueta]
    for clave, valor in (nodo.get("attr") or {}).items():
        valor = str(valor)
        if valor == "currentColor":
            valor = "param(fill) #000000"
        partes.append(f'{_atributo(clave)}="{_escapar(valor)}"')
    hijos = "".join(_nodo(h) for h in nodo.get("child") or [] if isinstance(h, dict))
    if hijos:
        return f"<{' '.join(partes)}>{hijos}</{etiqueta}>"
    return f"<{' '.join(partes)}/>"


def _atributo(clave):
    # React usa camelCase (strokeWidth); SVG, guiones (stroke-width).
    if clave in ("viewBox",):
        return clave
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), clave)


def _escapar(valor):
    return valor.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
