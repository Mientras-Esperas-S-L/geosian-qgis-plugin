"""Cómo se ve un mapa en GCC: orden, carpetas, visibilidad y vistas activas.

Sale de ``/api/v1/user-map-settings/by-map/<id>/`` y se interpreta como el
frontal (``layerTree.js``):

- En modo básico, que es el de partida, manda la estructura publicada en el
  mapa si la hay; si no, o en modo avanzado, la propia del usuario.
- ``layer_order`` mezcla capas (números) y carpetas (``"group:<id>"``). La
  primera es la de arriba del panel.
- Las carpetas están en ``layer_groups``, planas; la anidación la dan las
  referencias en ``children`` (o ``layerIds`` en el formato antiguo).
- Las capas que no aparecen en el árbol van al final, no desaparecen.
- Una capa que no está en ``visible_layers`` es visible.
- De ``active_view_ids`` vale la primera vista de cada capa.

Sin QGIS delante, para probarlo aparte.
"""

GROUP_PREFIX = "group:"


def layer_tree(ajustes, layer_ids):
    """Árbol de nodos para las capas ``layer_ids`` del mapa.

    Returns:
        Lista de nodos ``("layer", id)`` o ``("group", nombre, expandido,
        hijos)``, de arriba abajo.
    """
    orden, grupos = _structure(ajustes or {})
    conocidas = [int(i) for i in layer_ids]
    disponibles = set(conocidas)
    usadas = set()
    abiertos = set()

    def recorrer(elementos):
        nodos = []
        for elemento in elementos or []:
            if str(elemento).startswith(GROUP_PREFIX):
                gid = str(elemento)[len(GROUP_PREFIX):]
                grupo = grupos.get(gid)
                if not isinstance(grupo, dict) or gid in abiertos:
                    continue
                abiertos.add(gid)
                hijos = recorrer(_children(grupo))
                nodos.append(
                    ("group", str(grupo.get("name") or gid), grupo.get("expanded", True) is not False, hijos)
                )
                continue
            try:
                lid = int(elemento)
            except (TypeError, ValueError):
                continue
            if lid in disponibles and lid not in usadas:
                usadas.add(lid)
                nodos.append(("layer", lid))
        return nodos

    nodos = recorrer(orden)
    for lid in conocidas:
        if lid not in usadas:
            usadas.add(lid)
            nodos.append(("layer", lid))
    return nodos


def _structure(ajustes):
    propios = ajustes.get("settings") or {}
    publicada = ajustes.get("map_structure")
    modo = propios.get("layer_panel_mode") or "basic"
    if modo == "basic" and isinstance(publicada, dict):
        return publicada.get("layer_order") or [], publicada.get("layer_groups") or {}
    return propios.get("layer_order") or [], propios.get("layer_groups") or {}


def _children(grupo):
    if isinstance(grupo.get("children"), list):
        return grupo["children"]
    return grupo.get("layerIds") or []


def hidden_layers(ajustes):
    """Capas que el usuario tiene apagadas."""
    visibles = ((ajustes or {}).get("settings") or {}).get("visible_layers") or {}
    ocultas = set()
    for clave, valor in visibles.items():
        if valor is False:
            try:
                ocultas.add(int(clave))
            except (TypeError, ValueError):
                continue
    return ocultas


def active_views(ajustes, vistas_por_capa):
    """``{layer_id: vista}`` con la vista activa de cada capa.

    Args:
        vistas_por_capa: ``{layer_id: [vista, ...]}``, como lo da
            ``map_views``. Las vistas que ya no existen se descartan.
    """
    activas = ((ajustes or {}).get("settings") or {}).get("active_view_ids") or []
    por_id = {}
    for capa, vistas in (vistas_por_capa or {}).items():
        for vista in vistas or []:
            if isinstance(vista, dict) and vista.get("id") is not None:
                por_id[vista["id"]] = (int(capa), vista)
    salida = {}
    for vid in activas:
        try:
            vid = int(vid)
        except (TypeError, ValueError):
            continue
        if vid in por_id:
            capa, vista = por_id[vid]
            salida.setdefault(capa, vista)
    return salida
