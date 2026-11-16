from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("soportes/<int:pk>/detalle/", views.soporte_detalle, name="soportes_detalle"),
    path("equipos/<int:pk>/mover/", views.equipo_mover, name="equipos_mover"),
    path("soportes/solicitar/", views.soporte_solicitar, name="soportes_solicitar"),
    path("notificaciones/resumen/", views.notificaciones_resumen, name="notificaciones_resumen"),
    path("notificaciones/leer-todas/", views.notificaciones_leer_todas, name="notificaciones_leer_todas"),
    path("notificaciones/<int:pk>/abrir/", views.notificaciones_abrir, name="notificaciones_abrir"),
]

for k in views.LISTAS:
    urlpatterns += [
        path(f"{k}/", views.lista, {"clave": k}, name=k),
        path(f"{k}/excel/", views.exportar, {"clave": k}, name=f"{k}_excel"),
    ]

for k in views.CRUD:
    urlpatterns += [
        path(f"{k}/nuevo/", views.crear, {"clave": k}, name=f"{k}_nuevo"),
        path(f"{k}/<int:pk>/editar/", views.editar, {"clave": k}, name=f"{k}_editar"),
        path(f"{k}/<int:pk>/eliminar/", views.eliminar, {"clave": k}, name=f"{k}_eliminar"),
    ]
