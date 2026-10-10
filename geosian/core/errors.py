"""Errores del cliente de Geosian.

Se distinguen para que la interfaz pueda reaccionar distinto a cada uno: una
credencial caducada pide volver a entrar, un fallo de red ofrece reintentar y
un conflicto abre el diálogo de comparación.
"""


class GeosianError(Exception):
    """Raíz de todos los errores del complemento."""


class NetworkError(GeosianError):
    """No se pudo hablar con el servidor: sin red, DNS, tiempo agotado, TLS."""


class HttpError(GeosianError):
    """El servidor respondió con un código de error."""

    def __init__(self, status, message, body=None, url=None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.url = url

    def __str__(self):
        base = super().__str__()
        return f"HTTP {self.status}: {base}" if self.status else base


class AuthError(HttpError):
    """401. La credencial no vale o ha caducado: hay que volver a entrar."""


class ForbiddenError(HttpError):
    """403. La credencial vale, pero el usuario no tiene permiso para eso.

    No es lo mismo que un 401: volver a entrar no lo arregla. Tratarlo igual
    abría el diálogo de conexión al desplegar un mapa sin permiso sobre sus
    capas, y se quedaba ahí.
    """


class ConflictError(HttpError):
    """409. Alguien tocó el elemento desde que lo leímos.

    Reservado para la fase 2 (bloqueo optimista). Se define aquí para que el
    cliente ya sepa traducir el código y no haya que tocarlo después.
    """


class NotFoundError(HttpError):
    """404. El recurso no existe o el usuario no tiene permiso para verlo."""


class ApiError(HttpError):
    """Cualquier otra respuesta de error de la API."""
