from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Bitacora, Categoria, Centro, Equipo, Gerencia, Notificacion, Soporte, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Mesa de ayuda", {"fields": ("cargo", "rol", "gerencia", "centro")}),)
    list_display = ("username", "first_name", "last_name", "rol", "gerencia", "is_active")


admin.site.register([Gerencia, Centro, Categoria, Equipo, Soporte, Bitacora, Notificacion])
