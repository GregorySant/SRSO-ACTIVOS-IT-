from django.conf import settings
from django.contrib.auth.models import AnonymousUser


class SesionPorArranqueMiddleware:
    """Si el servidor se reinició desde que se inició la sesión, se descarta y se pide el login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.CERRAR_SESION_AL_REINICIAR and request.user.is_authenticated:
            if request.session.get("arranque") != settings.ARRANQUE_ID:
                request.session.flush()
                request.user = AnonymousUser()
        return self.get_response(request)
