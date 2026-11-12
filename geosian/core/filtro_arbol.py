"""Condiciones combinadas: el filtro en árbol de GreenCityControl, sin Qt.

El mismo formato que el constructor de la web (``src/utils/filtroArbol.js``) y que el
servidor interpreta en el parámetro ``filtro``::

    {"todas": True, "condiciones": [
        {"campo": "zona", "op": "es_uno_de", "valor": ["Viaria"]},
        {"todas": False, "condiciones": [...]},                    # un nivel de grupos
        {"partes": "parte_trabajo", "tiene": False,                # bloque de partes
         "periodo": {"ultimos_dias": 30}, "ultimo": False,
         "todas": True, "condiciones": [{"campo": "riego", "op": "no_vacio"}]}]}

Aquí va la lógica que no depende de la ventana: los operadores de cada tipo de campo,
la forma del valor de cada operador, la limpieza antes de mandarlo y la frase en llano.
"""

from . import schema as S

OPERADORES = {
    "lista": [
        ("es_uno_de", "es uno de"),
        ("no_es_uno_de", "no es ninguno de"),
        ("vacio", "está vacío"),
        ("no_vacio", "no está vacío"),
    ],
    "casillas": [
        ("tiene_alguno", "tiene alguno de"),
        ("tiene_todos", "tiene todos"),
        ("no_tiene", "no tiene ninguno de"),
        ("vacio", "está vacío"),
        ("no_vacio", "no está vacío"),
    ],
    "numero": [
        ("gt", "mayor que"),
        ("gte", "mayor o igual que"),
        ("lt", "menor que"),
        ("lte", "menor o igual que"),
        ("eq", "igual a"),
        ("entre", "entre"),
        ("vacio", "está vacío"),
        ("no_vacio", "no está vacío"),
    ],
    "fecha": [
        ("antes", "antes del"),
        ("despues", "después del"),
        ("entre", "entre"),
        ("ultimos_dias", "en los últimos (días)"),
        ("vacio", "está vacío"),
        ("no_vacio", "no está vacío"),
    ],
    "texto": [
        ("contiene", "contiene"),
        ("no_contiene", "no contiene"),
        ("es", "es exactamente"),
        ("empieza", "empieza por"),
        ("vacio", "está vacío"),
        ("no_vacio", "no está vacío"),
    ],
}

_ETIQUETAS = {op: texto for lista in OPERADORES.values() for op, texto in lista}
_OPS_LISTA = {"es_uno_de", "no_es_uno_de", "tiene_alguno", "tiene_todos", "no_tiene"}
_OPS_SIN_VALOR = {"vacio", "no_vacio"}


def tipo_de_campo(attr):
    """El tipo de filtro de un atributo del LAD."""
    if not attr:
        return "texto"
    if S.is_multiple(attr):
        return "casillas"
    if S.allowed_values(attr) or attr.get("type") in S.CHOICE_TYPES:
        return "lista"
    if attr.get("type") in S.NUMERIC_TYPES:
        return "numero"
    if attr.get("type") in S.DATE_TYPES or attr.get("type") in ("date", "datetime"):
        return "fecha"
    return "texto"


def operadores_de(tipo):
    return OPERADORES.get(tipo, OPERADORES["texto"])


def etiqueta(op):
    return _ETIQUETAS.get(op, op)


def forma_del_valor(op):
    """'lista', 'rango', 'ninguno' o 'escalar'."""
    if op in _OPS_SIN_VALOR:
        return "ninguno"
    if op in _OPS_LISTA:
        return "lista"
    if op == "entre":
        return "rango"
    return "escalar"


def valor_inicial(op):
    forma = forma_del_valor(op)
    return {"lista": [], "rango": {"desde": "", "hasta": ""}, "ninguno": None}.get(forma, "")


def convertir_valor(valor, op_anterior, op_nuevo):
    """El valor al cambiar de operador, conservando lo escrito cuando se puede."""
    de, a = forma_del_valor(op_anterior), forma_del_valor(op_nuevo)
    if de == a:
        return valor
    if a == "ninguno":
        return None
    if a == "lista":
        if isinstance(valor, list):
            return valor
        return [valor] if valor not in ("", None) and not isinstance(valor, dict) else []
    if a == "rango":
        primero = valor[0] if isinstance(valor, list) and valor else ("" if isinstance(valor, dict) else valor)
        return {"desde": primero or "", "hasta": ""}
    if isinstance(valor, list):
        return valor[0] if valor else ""
    if isinstance(valor, dict):
        return valor.get("desde") or ""
    return valor if valor is not None else ""


def condicion_nueva(campo, tipo):
    op = operadores_de(tipo)[0][0]
    return {"campo": campo, "op": op, "valor": valor_inicial(op)}


def _vacio(valor):
    return valor is None or (isinstance(valor, str) and not valor.strip())


def condicion_completa(c):
    if not c or not c.get("campo") or not c.get("op"):
        return False
    forma = forma_del_valor(c["op"])
    valor = c.get("valor")
    if forma == "ninguno":
        return True
    if forma == "lista":
        return isinstance(valor, list) and any(not _vacio(v) for v in valor)
    if forma == "rango":
        return isinstance(valor, dict) and (not _vacio(valor.get("desde")) or not _vacio(valor.get("hasta")))
    return not _vacio(valor)


def es_partes(nodo):
    return isinstance(nodo, dict) and "partes" in nodo


def es_grupo(nodo):
    return isinstance(nodo, dict) and isinstance(nodo.get("condiciones"), list) and "partes" not in nodo


def _limpiar_condicion(c):
    forma = forma_del_valor(c["op"])
    limpia = {"campo": c["campo"], "op": c["op"]}
    if forma == "lista":
        limpia["valor"] = [v.strip() if isinstance(v, str) else v for v in c["valor"] if not _vacio(v)]
    elif forma == "escalar":
        limpia["valor"] = c["valor"].strip() if isinstance(c["valor"], str) else c["valor"]
    elif forma == "rango":
        limpia["valor"] = c["valor"]
    return limpia


def _periodo(periodo):
    if not periodo:
        return None
    if not _vacio(periodo.get("ultimos_dias")):
        try:
            return {"ultimos_dias": int(str(periodo["ultimos_dias"]).strip())}
        except ValueError:
            return None
    limpio = {k: periodo[k] for k in ("desde", "hasta") if not _vacio(periodo.get(k))}
    return limpio or None


def limpiar_arbol(arbol):
    """El árbol listo para mandar, o None si no queda nada que filtrar."""
    if not isinstance(arbol, dict) or not isinstance(arbol.get("condiciones"), list):
        return None

    def limpiar(nodo):
        if es_partes(nodo):
            bloque = {
                "partes": nodo.get("partes") or None,
                "tiene": nodo.get("tiene", True) is not False,
                "todas": nodo.get("todas", True) is not False,
                "ultimo": bool(nodo.get("ultimo")),
                "condiciones": [_limpiar_condicion(c) for c in nodo.get("condiciones") or [] if condicion_completa(c)],
            }
            periodo = _periodo(nodo.get("periodo"))
            if periodo:
                bloque["periodo"] = periodo
            return bloque
        if es_grupo(nodo):
            hijos = [h for h in (limpiar(x) for x in nodo["condiciones"]) if h]
            return {"todas": nodo.get("todas", True) is not False, "condiciones": hijos} if hijos else None
        return _limpiar_condicion(nodo) if condicion_completa(nodo) else None

    raiz = limpiar({"todas": arbol.get("todas", True), "condiciones": arbol["condiciones"]})
    return raiz if raiz and raiz["condiciones"] else None


def frase_del_arbol(arbol, titulo_de_campo=lambda nombre, partes=None: nombre, titulo_de_formulario=lambda n: n):
    """El filtro en llano, para leerlo antes de aplicarlo."""
    limpio = limpiar_arbol(arbol)
    if not limpio:
        return "Todos los elementos"

    def valor(c):
        forma = forma_del_valor(c["op"])
        if forma == "ninguno":
            return ""
        if forma == "lista":
            return " " + ", ".join(str(v) for v in c["valor"])
        if forma == "rango":
            return f" {c['valor'].get('desde') or '…'} y {c['valor'].get('hasta') or '…'}"
        return f" {c['valor']}"

    def condicion(c, partes=None):
        return f"{titulo_de_campo(c['campo'], partes)} {etiqueta(c['op'])}{valor(c)}"

    def bloque(b):
        nombre = titulo_de_formulario(b["partes"]) if b["partes"] else "cualquier tipo"
        texto = f"{'con algún' if b['tiene'] else 'sin ningún'} parte de {nombre}"
        periodo = b.get("periodo") or {}
        if "ultimos_dias" in periodo:
            texto += f" en los últimos {periodo['ultimos_dias']} días"
        elif periodo:
            texto += f" entre {periodo.get('desde') or '…'} y {periodo.get('hasta') or '…'}"
        if b["ultimo"]:
            texto += " (solo el último)"
        if b["condiciones"]:
            union = " y " if b["todas"] else " o "
            texto += ": " + union.join(condicion(c, b["partes"]) for c in b["condiciones"])
        return texto

    def nodo(n, raiz=False):
        if es_partes(n):
            return bloque(n)
        if es_grupo(n):
            dentro = (" y " if n["todas"] else " o ").join(nodo(h) for h in n["condiciones"])
            return dentro if raiz or len(n["condiciones"]) == 1 else f"({dentro})"
        return condicion(n)

    return nodo(limpio, raiz=True)
