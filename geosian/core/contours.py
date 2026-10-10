"""Contornos como los pinta la web (``ContourLayer`` de deck.gl), sin QGIS delante.

Los puntos se agregan en una rejilla de ``cellSize`` metros (suma o media de su peso)
y cada ``threshold`` de la vista da una isolínea: el borde de las celdas que llegan a
ese valor, interpolado entre centros de celda (``marching squares``). Las coordenadas
van en metros, en EPSG:3857, como las mide la web.
"""

import math


class Grid:
    """Valor por celda; las que no tienen puntos valen 0."""

    def __init__(self, cell, x0, y0, valores):
        self.cell = float(cell)
        self.x0 = x0
        self.y0 = y0
        self._valores = valores

    def value(self, i, j):
        return self._valores.get((i, j), 0.0)

    def center(self, i, j):
        return (self.x0 + (i + 0.5) * self.cell, self.y0 + (j + 0.5) * self.cell)

    def bounds(self):
        """``(imin, jmin, imax, jmax)`` de las celdas con valor, o ``None``."""
        if not self._valores:
            return None
        ies = [i for i, _ in self._valores]
        jotas = [j for _, j in self._valores]
        return min(ies), min(jotas), max(ies), max(jotas)


def grid(puntos, cell, aggregation="SUM"):
    """Rejilla de ``cell`` metros con ``puntos`` ``(x, y, peso)``.

    ``aggregation``: ``SUM`` (la de la web por omisión) o ``MEAN``.
    """
    cell = float(cell)
    if not puntos:
        return Grid(cell, 0.0, 0.0, {})
    x0 = math.floor(min(p[0] for p in puntos) / cell) * cell
    y0 = math.floor(min(p[1] for p in puntos) / cell) * cell
    sumas, cuentas = {}, {}
    for x, y, peso in puntos:
        clave = (int((x - x0) // cell), int((y - y0) // cell))
        sumas[clave] = sumas.get(clave, 0.0) + float(peso)
        cuentas[clave] = cuentas.get(clave, 0) + 1
    if str(aggregation).upper() == "MEAN":
        valores = {k: sumas[k] / cuentas[k] for k in sumas}
    else:
        valores = sumas
    return Grid(cell, x0, y0, valores)


# Para cada caso de marching squares, los pares de aristas que une un segmento.
# Aristas: 0 abajo, 1 derecha, 2 arriba, 3 izquierda.
_CASOS = {
    1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 6: [(0, 2)], 7: [(3, 2)],
    8: [(2, 3)], 9: [(0, 2)], 11: [(1, 2)], 12: [(1, 3)], 13: [(0, 1)], 14: [(3, 0)],
}


def isolines(rejilla, umbral):
    """Segmentos ``((x1, y1), (x2, y2))`` de la isolínea de ``umbral``."""
    limites = rejilla.bounds()
    if limites is None:
        return []
    imin, jmin, imax, jmax = limites
    t = float(umbral)
    segmentos = []
    # Un borde de celdas vacías alrededor, para que las líneas se cierren.
    for i in range(imin - 1, imax + 1):
        for j in range(jmin - 1, jmax + 1):
            esquinas = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            v = [rejilla.value(*e) for e in esquinas]
            caso = sum(1 << k for k in range(4) if v[k] >= t)
            if caso in (0, 15):
                continue
            puntos = [rejilla.center(*e) for e in esquinas]

            if caso in (5, 10):
                # Silla: decide el valor del centro del cuadrado.
                centro = sum(v) / 4.0
                if (centro >= t) == (caso == 5):
                    pares = [(3, 2), (1, 0)] if caso == 5 else [(0, 1), (2, 3)]
                else:
                    pares = [(3, 0), (1, 2)] if caso == 5 else [(3, 2), (1, 0)]
            else:
                pares = _CASOS[caso]
            for a, b in pares:
                segmentos.append((_arista(v, puntos, t, a), _arista(v, puntos, t, b)))
    return segmentos


def _arista(v, puntos, t, n):
    """Dónde cruza ``t`` la arista ``n`` del cuadrado, interpolando entre esquinas."""
    a, b = n, (n + 1) % 4
    va, vb = v[a], v[b]
    f = 0.5 if vb == va else (t - va) / (vb - va)
    (xa, ya), (xb, yb) = puntos[a], puntos[b]
    return (xa + (xb - xa) * f, ya + (yb - ya) * f)
