from django.conf import settings

_ESTATICOS = ("css/app.css", "js/app.js")


def _version_estaticos():
    """Fecha de modificación de los estáticos propios: cambia el enlace y fuerza la recarga en el navegador."""
    try:
        return int(max((settings.BASE_DIR / "static" / f).stat().st_mtime for f in _ESTATICOS))
    except OSError:
        return 0


def globales(request):
    match = getattr(request, "resolver_match", None)
    nombre = (match.url_name if match and match.url_name else "") or ""
    u = getattr(request, "user", None)
    sin_asignar = bool(u is not None and u.is_authenticated and not u.ve_todo
                       and (not u.gerencia_id or (u.es_solicitante and not u.centro_id)))
    return {
        "sin_asignar": sin_asignar,
        "ASSET_V": _version_estaticos(),
        "APP_NAME": settings.NOMBRE_APP,
        "LOGO": settings.LOGO,
        "url_name": nombre,
        "seccion": nombre.split("_")[0],   # 'equipos_nuevo' -> 'equipos' (abre el grupo del menú)
    }
