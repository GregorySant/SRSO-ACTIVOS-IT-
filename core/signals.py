from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .utils import registrar


@receiver(user_logged_in)
def al_iniciar_sesion(sender, request, user, **kwargs):
    if request is not None:
        request.session["arranque"] = settings.ARRANQUE_ID
    registrar(user, "LOGIN", "Sesión", "Inició sesión")


@receiver(user_logged_out)
def al_cerrar_sesion(sender, request, user, **kwargs):
    if user:
        registrar(user, "LOGOUT", "Sesión", "Cerró sesión")
