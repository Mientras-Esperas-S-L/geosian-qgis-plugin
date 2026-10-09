"""La URI del proveedor.

    geosian://<conexión>/map/<map_id>/layer/<layer_id>?geometry_type=points&view=3
    geosian://<conexión>/map/<map_id>/layer/<layer_id>/info/<nombre>?geometry_type=points

La segunda es una tabla sin geometría con los partes (información adicional) de
un tipo, que se relaciona con su capa por ``geodata_id``.

Los filtros por partes del panel de la web van como ``parte=<tipo>__<campo>=<valor>``
(con ``__gte``, ``__gt``, ``__lte`` o ``__lt`` tras el campo para los números; el
mismo campo repetido es «o») y las fechas de los partes como ``date_from``,
``date_to`` (``AAAA-MM-DD``) y ``most_recent=1``. Los resuelve el servidor.

``<conexión>`` es el nombre de una conexión guardada en los ajustes de QGIS, no
un servidor. Así la URI no lleva ni la dirección ni la credencial, que es lo que
hay que evitar: un proyecto ``.qgs`` se comparte por correo y no debe llevar
dentro el token de nadie.
"""

from urllib.parse import parse_qs, quote, unquote, urlparse

SCHEME = "geosian"


class LayerUri:
    """Partes de una URI del proveedor."""

    def __init__(self, connection, map_id, layer_id, geometry_type=None,
                 view_id=None, crs="EPSG:4326", info_name=None, subset="",
                 partes=None, date_from=None, date_to=None, most_recent=False):
        self.connection = connection
        self.map_id = int(map_id)
        self.layer_id = int(layer_id)
        self.geometry_type = geometry_type
        self.view_id = int(view_id) if view_id else None
        self.crs = crs
        self.info_name = info_name or None
        # El filtro de la capa («Filtrar…»). Va en la URI porque es lo que QGIS
        # guarda en el proyecto; fuera de ella se perdería al reabrirlo.
        self.subset = subset or ""
        # Filtros por partes: pares (<tipo>__<campo>[__op], valor), en orden.
        self.partes = list(partes or [])
        self.date_from = date_from or None
        self.date_to = date_to or None
        self.most_recent = bool(most_recent)

    def server_filters(self, zona_horaria):
        """Los filtros por partes y fechas como los manda la web a la API.

        Args:
            zona_horaria: la del equipo (``Europe/Madrid``), para que «desde» y
                «hasta» sean días enteros de aquí y no de UTC.
        """
        params = {}
        for clave, valor in self.partes:
            params.setdefault(f"attr__{clave}", []).append(valor)
        if self.date_from:
            params["date_from"] = self.date_from
        if self.date_to:
            params["date_to"] = self.date_to
        if (self.date_from or self.date_to) and zona_horaria:
            params["timezone"] = zona_horaria
        if self.most_recent:
            params["most_recent"] = "true"
        return params

    def __str__(self):
        base = (
            f"{SCHEME}://{quote(self.connection)}"
            f"/map/{self.map_id}/layer/{self.layer_id}"
        )
        if self.info_name:
            base += f"/info/{quote(self.info_name)}"
        params = []
        if self.geometry_type:
            params.append(f"geometry_type={self.geometry_type}")
        if self.view_id:
            params.append(f"view={self.view_id}")
        if self.crs and self.crs != "EPSG:4326":
            params.append(f"crs={self.crs}")
        if self.subset:
            params.append(f"subset={quote(self.subset, safe='')}")
        for clave, valor in self.partes:
            params.append(f"parte={quote(f'{clave}={valor}', safe='')}")
        if self.date_from:
            params.append(f"date_from={self.date_from}")
        if self.date_to:
            params.append(f"date_to={self.date_to}")
        if self.most_recent:
            params.append("most_recent=1")
        return base + ("?" + "&".join(params) if params else "")

    def __eq__(self, otro):
        return isinstance(otro, LayerUri) and str(self) == str(otro)

    def __repr__(self):
        return f"<LayerUri {self}>"


def parse_uri(uri):
    """Interpreta una URI del proveedor.

    Raises:
        ValueError: si no tiene la forma esperada. El proveedor lo traduce en
            una capa inválida con un mensaje que el usuario pueda entender.
    """
    if not uri:
        raise ValueError("URI vacía")

    partes = urlparse(uri)
    if partes.scheme != SCHEME:
        raise ValueError(f"Esquema desconocido: {partes.scheme!r}, se esperaba {SCHEME!r}")

    conexion = unquote(partes.netloc or "")
    if not conexion:
        raise ValueError("Falta el nombre de la conexión")

    segmentos = [s for s in (partes.path or "").split("/") if s]
    valores = {}
    for i in range(0, len(segmentos) - 1, 2):
        valores[segmentos[i]] = segmentos[i + 1]

    if "map" not in valores or "layer" not in valores:
        raise ValueError("La ruta debe ser /map/<id>/layer/<id>")

    try:
        map_id = int(valores["map"])
        layer_id = int(valores["layer"])
    except (TypeError, ValueError):
        raise ValueError("Los identificadores de mapa y capa deben ser números")

    consulta = parse_qs(partes.query or "")

    def uno(clave, defecto=None):
        valor = consulta.get(clave)
        return valor[0] if valor else defecto

    return LayerUri(
        connection=conexion,
        map_id=map_id,
        layer_id=layer_id,
        geometry_type=uno("geometry_type"),
        view_id=uno("view"),
        crs=uno("crs", "EPSG:4326"),
        info_name=unquote(valores["info"]) if valores.get("info") else None,
        subset=uno("subset", ""),
        partes=[_parte(texto) for texto in consulta.get("parte", [])],
        date_from=uno("date_from"),
        date_to=uno("date_to"),
        most_recent=uno("most_recent") in ("1", "true"),
    )


def _parte(texto):
    """``<tipo>__<campo>[__op]=<valor>`` → ``(clave, valor)``."""
    clave, igual, valor = texto.partition("=")
    tipo, _, campo = clave.partition("__")
    if not igual or not tipo or not campo:
        raise ValueError(
            f"Filtro de partes no válido: {texto!r}; se esperaba <tipo>__<campo>=<valor>"
        )
    return clave, valor


def build_uri(connection, map_id, layer_id, geometry_type=None, view_id=None,
              info_name=None):
    return str(
        LayerUri(connection, map_id, layer_id, geometry_type, view_id, info_name=info_name)
    )
