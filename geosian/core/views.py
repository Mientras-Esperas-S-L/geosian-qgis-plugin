"""Vistas de capa de Geosian, sin QGIS delante.

Una vista es un filtro (``filter_config``) y un estilo (``style_config``)
guardados sobre una capa. El estilo lo interpreta ``styles``; aquí se traduce el
filtro a los parámetros ``attr__…`` de la API.

Se traduce como lo hace el frontal al activar una vista
(``convertFilterConfigToFilterCriteria`` + ``buildFilterParams``) y no con el
``view_ids`` del servidor, aunque exista: el del servidor une los grupos con OR
e ignora ``gte`` y ``lte``, que son justo los que escribe el editor de vistas
para los rangos. Comprobado en devel: una vista de diámetro entre 10 y 90
devolvía la capa entera por ``view_ids`` y 54 elementos por ``attr__``, que es
lo que ve el usuario en la web.

Lo que el frontal pierde al traducir también se pierde aquí, a propósito, para
que la vista sea la misma en los dos sitios: todo se une con AND y los
operadores que no sean ``in``, ``contains``, ``equals``, ``gte`` o ``lte`` se
descartan.
"""

_SUFIJOS = {"contains": "__contains", "gte": "__gte", "lte": "__lte"}


def filter_params(filter_config):
    """Parámetros de la API para el ``filter_config`` de una vista.

    Returns:
        ``(parámetros, avisos)``. Los parámetros son un diccionario cuyos
        valores pueden ser listas, para los ``in`` (``attr__f=a&attr__f=b``).
    """
    config = filter_config if isinstance(filter_config, dict) else {}
    params = {}
    avisos = []

    for grupo in config.get("query_groups") or []:
        if not isinstance(grupo, dict):
            continue
        contexto = grupo.get("context") or "elements"
        fuente = grupo.get("source_name")
        for regla in grupo.get("rules") or []:
            if not isinstance(regla, dict) or not regla.get("field"):
                continue
            campo = str(regla["field"])
            operador = str(regla.get("operator") or "").lower()
            valor = regla.get("value")

            if contexto == "global":
                _global(params, campo, operador, valor, avisos)
                continue

            if contexto == "additional_info" and "__" not in campo and fuente:
                campo = f"{fuente}__{campo}"
            elif contexto == "elements" and "__" in campo:
                # «valor_de_sección__campo»: el frontal lo manda por
                # filter_groups, que depende de las dependencias del esquema.
                # Aquí se filtra por el campo, sin la sección.
                avisos.append(
                    f"El filtro sobre «{campo}» depende de una sección; se aplica "
                    "sobre el campo sin distinguir la sección."
                )
                campo = campo.split("__")[-1]

            clave = f"attr__{campo}"
            if operador == "in":
                valores = valor if isinstance(valor, list) else [valor]
                valores = [_texto(v) for v in valores if v is not None and v != ""]
                if valores:
                    params.setdefault(clave, [])
                    params[clave].extend(valores)
            elif operador in _SUFIJOS:
                if valor is not None and valor != "":
                    params[clave + _SUFIJOS[operador]] = _texto(valor)
            elif operador == "equals":
                if valor is not None and valor != "":
                    params[clave] = _texto(valor)
            else:
                avisos.append(
                    f"La regla «{campo} {operador}» no se aplica: la web tampoco la aplica "
                    "al activar la vista."
                )

    return params, avisos


def _global(params, campo, operador, valor, avisos):
    if campo == "_created_at" and operador in ("gte", "lte") and valor:
        params["date_from" if operador == "gte" else "date_to"] = str(valor)
        params.setdefault("timezone", "Europe/Madrid")
    elif campo == "_most_recent" and valor in (True, "true", "True"):
        params["most_recent"] = "true"
    else:
        avisos.append(f"El filtro global «{campo}» no se aplica.")


def _texto(valor):
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def is_element_view(vista):
    """Las vistas de información adicional muestran registros, no elementos."""
    return (vista or {}).get("context_type", "elements") in ("", None, "elements")


def is_overlay(style_config):
    """True si la vista se pinta ENCIMA de su capa en vez de sustituirla.

    Como en la web (``useMvtLayers.js``): las vistas de color
    (``visualization`` «default» o sin ella) re-pintan la misma geometría y
    ocultan la capa base; las de icono, calor, hexágonos, contornos o H3 son
    superposiciones y la base sigue visible debajo.
    """
    config = style_config if isinstance(style_config, dict) else {}
    return (config.get("visualization") or "default") != "default"
