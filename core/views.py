from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import forms as f
from .models import Bitacora, Categoria, Centro, Equipo, Gerencia, Notificacion, Soporte, Usuario
from .utils import (accion_de_edicion, asignar_pendientes, asignar_tecnico, avisar_cambios_soporte, avisar_solicitud_nueva, cambios, describir, export_xlsx,
                    registrar, valores)

# ============================================================================
#  Utilidades
# ============================================================================
COLOR_EQ = {"Operativo": "success", "Dañado": "danger", "En reparación": "warning", "Desincorporado": "secondary"}
COLOR_SOP = {"Pendiente": "warning", "En proceso": "info", "Resuelto": "success"}


def nivel_ok(user, nivel):
    return {"todos": True, "interno": not user.es_solicitante, "editor": user.puede_editar,
            "admin": user.es_admin, "solicitante": user.es_solicitante and bool(user.centro_id),
            "notificable": user.recibe_notificaciones}[nivel]


# Segmentación por rol: Administrador y Solo consulta ven todo; el Técnico, solo su gerencia; el Solicitante,
# solo su centro. Si el usuario no tiene la asignación, no ve nada.
ALCANCE = {Equipo: ("centro__gerencia_id", "centro_id"), Soporte: ("centro__gerencia_id", "centro_id"),
           Gerencia: ("pk", None), Centro: ("gerencia_id", "pk")}


def visibles(user, modelo):
    qs = modelo.objects.all()
    if modelo not in ALCANCE or user.ve_todo:
        return qs
    por_gerencia, por_centro = ALCANCE[modelo]
    if user.es_solicitante:
        return qs.filter(**{por_centro: user.centro_id}) if por_centro and user.centro_id else qs.none()
    return qs.filter(**{por_gerencia: user.gerencia_id}) if user.gerencia_id else qs.none()


def exigir(request, nivel):
    if not nivel_ok(request.user, nivel):
        raise PermissionDenied


def fecha_txt(d):
    return timezone.localtime(d).strftime("%d/%m/%Y %H:%M") if d else ""


def fecha_dia(d):
    return timezone.localtime(d).strftime("%d/%m/%Y") if d else ""


def badge(texto, colores):
    return format_html('<span class="badge text-bg-{}">{}</span>', colores.get(texto, "secondary"), texto)


def A(nombre, pk, icono, titulo, clase="secondary", modal=False):
    return {"url": reverse(nombre, args=[pk]), "icono": icono, "titulo": titulo, "clase": clase, "modal": modal}


def buscar(qs, r, campos, param="q"):
    q = r.GET.get(param, "").strip()
    if q:
        cond = Q()
        for c in campos:
            cond |= Q(**{f"{c}__icontains": q})
        qs = qs.filter(cond)
    return qs


def filtrar(qs, r, mapa):
    for param, campo in mapa.items():
        v = r.GET.get(param)
        if v:
            try:
                qs = qs.filter(**{campo: v})
            except (ValueError, TypeError, ValidationError):
                pass
    return qs


def fechas(qs, r, campo):
    for param, op in (("desde", "gte"), ("hasta", "lte")):
        v = r.GET.get(param)
        if v:
            try:
                qs = qs.filter(**{f"{campo}__date__{op}": v})
            except (ValueError, ValidationError):
                pass
    return qs


def nombres_solicitantes(user):
    """Nombres de quienes han pedido soportes dentro de lo que el usuario puede ver."""
    return [n for n in visibles(user, Soporte).order_by("solicitante").values_list("solicitante", flat=True).distinct() if n]


def sel(r, name, label, opciones):
    """opciones: (valor, texto) o (valor, texto, gerencia_id) para que el filtro de centros dependa de la gerencia."""
    return {"tipo": "select", "name": name, "label": label, "valor": r.GET.get(name, ""),
            "opciones": [(str(o[0]), o[1], o[2] if len(o) > 2 else "") for o in opciones]}


def rango(r):
    return [{"tipo": "date", "name": n, "label": t, "valor": r.GET.get(n, "")}
            for n, t in (("desde", "Desde"), ("hasta", "Hasta"))]


def op_gerencias(user):
    return [(g.pk, g.nombre) for g in visibles(user, Gerencia)]


def op_centros(user):
    return [(c.pk, f"{c.nombre} ({c.gerencia.nombre})", c.gerencia_id)
            for c in visibles(user, Centro).select_related("gerencia")]


# ============================================================================
#  Campos que se comparan para detallar cambios en la bitácora
# ============================================================================
C_EQUIPO = [("nombre_equipo", "Equipo"), ("marca", "Marca"), ("modelo", "Modelo"), ("serial", "Serial"),
            ("activo_fijo", "Activo fijo"), ("ubicacion", "Ubicación"), ("area", "Área"),
            ("cantidad", "Cantidad"), ("estatus", "Estatus")]
C_SOPORTE = [("ubicacion", "Ubicación"), ("area", "Área"), ("motivo", "Motivo"), ("hallazgo", "Hallazgo"), ("solucion", "Solución"),
             ("recomendaciones", "Recomendaciones"), ("solicitante", "Solicitó el servicio"), ("estatus", "Estatus"),
             ("tecnico", "Técnico")]
C_GERENCIA = [("nombre", "Nombre")]
C_CENTRO = [("gerencia", "Gerencia"), ("nombre", "Centro"), ("direccion", "Dirección"),
            ("geolocalizacion", "Geolocalización"), ("observaciones", "Observaciones")]
C_CATEGORIA = [("nombre", "Nombre"), ("descripcion", "Descripción")]
C_USUARIO = [("username", "Usuario"), ("first_name", "Nombre"), ("last_name", "Apellido"), ("cargo", "Cargo"),
             ("rol", "Rol"), ("gerencia", "Gerencia"), ("centro", "Centro"), ("is_active", "Activo")]


# ============================================================================
#  Definición de cada tabla (la misma función arma la tabla y el Excel)
# ============================================================================
def qs_equipos(r):
    qs = visibles(r.user, Equipo).select_related("categoria", "centro__gerencia")
    qs = buscar(qs, r, ["equipo_otro", "categoria__nombre", "marca", "modelo", "serial", "activo_fijo", "area",
                        "centro__nombre"])
    return filtrar(qs, r, {"gerencia": "centro__gerencia_id", "centro": "centro_id",
                           "categoria": "categoria_id", "marca": "marca", "estatus": "estatus"})


def filtros_equipos(r):
    return [sel(r, "gerencia", "Gerencia", op_gerencias(r.user)), sel(r, "centro", "Centro", op_centros(r.user)),
            sel(r, "categoria", "Equipo", [(c.pk, c.nombre) for c in Categoria.objects.all()]),
            sel(r, "marca", "Marca", [(m, m) for m in visibles(r.user, Equipo).order_by("marca")
                                      .values_list("marca", flat=True).distinct()])]


def fila_equipo(e):
    return [e.nombre_equipo, e.marca, e.modelo, e.serial, e.activo_fijo, e.centro.gerencia.nombre,
            e.centro.nombre, e.area, e.cantidad, e.get_estatus_display()]


def acc_equipo(u, e):
    a = []
    if u.puede_editar:
        a.append(A("equipos_mover", e.pk, "arrow-left-right", "Mover / cambiar estatus", "primary"))
    if u.es_admin:
        a += [A("equipos_editar", e.pk, "pencil", "Editar", "warning"),
              A("equipos_eliminar", e.pk, "trash", "Eliminar", "danger")]
    return a


def qs_soportes(r):
    qs = visibles(r.user, Soporte).select_related("centro__gerencia", "tecnico")
    qs = buscar(qs, r, ["motivo", "area", "hallazgo", "solucion", "recomendaciones", "solicitante",
                        "centro__nombre"])
    qs = filtrar(qs, r, {"gerencia": "centro__gerencia_id", "centro": "centro_id", "tecnico": "tecnico_id", "solicitante": "solicitante",
                           "estatus": "estatus"})
    return fechas(qs, r, "fecha")


def filtros_soportes(r):
    tecnicos = Usuario.objects.filter(pk__in=visibles(r.user, Soporte).values("tecnico_id")).order_by("username")
    return [sel(r, "gerencia", "Gerencia", op_gerencias(r.user)), sel(r, "centro", "Centro", op_centros(r.user)),
            sel(r, "tecnico", "Técnico", [(u.pk, str(u)) for u in tecnicos]),
            sel(r, "solicitante", "Solicitante", [(n, n) for n in nombres_solicitantes(r.user)])] + rango(r)


def fila_soporte(s):
    return [fecha_dia(s.fecha), s.centro.gerencia.nombre, s.centro.nombre, s.area, s.motivo, s.solicitante,
            str(s.tecnico) if s.tecnico else "", s.get_estatus_display()]


def acc_soporte(u, s):
    a = [A("soportes_detalle", s.pk, "eye", "Ver información", "info", modal=True)]
    if u.puede_editar:
        a.append(A("soportes_editar", s.pk, "pencil", "Editar", "warning"))
    if u.es_admin:
        a.append(A("soportes_eliminar", s.pk, "trash", "Eliminar", "danger"))
    return a


def acc_admin(clave):
    def _acc(u, o):
        if not u.es_admin:
            return []
        return [A(f"{clave}_editar", o.pk, "pencil", "Editar", "warning"),
                A(f"{clave}_eliminar", o.pk, "trash", "Eliminar", "danger")]
    return _acc


def acc_usuario(u, o):
    if not u.es_admin:
        return []
    a = [A("usuarios_editar", o.pk, "pencil", "Editar", "warning")]
    if o.pk != u.pk:
        a.append(A("usuarios_eliminar", o.pk, "trash", "Eliminar", "danger"))
    return a


def qs_bitacora(r):
    qs = buscar(Bitacora.objects.all(), r, ["usuario_nombre", "modulo", "detalle"])
    qs = filtrar(qs, r, {"usuario": "usuario_id", "accion": "accion", "modulo": "modulo"})
    return fechas(qs, r, "fecha")


LISTAS = {
    "equipos": dict(modulo="Equipos", titulo="Inventario de equipos", acceso="interno", nuevo="editor",
                    texto_nuevo="Registrar equipo", qs=qs_equipos, filtros=filtros_equipos, fila=fila_equipo,
                    cols=["Equipo", "Marca", "Modelo", "Serial", "Activo fijo", "Gerencia", "Centro", "Área",
                          "Cantidad", "Estatus"], badge=(9, COLOR_EQ), pastillas=Equipo.ESTATUS, acciones=acc_equipo),
    "soportes": dict(modulo="Soportes", titulo="Registro de soportes", acceso="interno", nuevo="editor",
                     texto_nuevo="Registrar soporte", qs=qs_soportes, filtros=filtros_soportes, fila=fila_soporte,
                     cols=["Fecha", "Gerencia", "Centro", "Área", "Motivo", "Solicitó el servicio", "Técnico", "Estatus"],
                     badge=(7, COLOR_SOP), pastillas=Soporte.ESTATUS, rapidos=True, acciones=acc_soporte),
    "gerencias": dict(modulo="Gerencias", titulo="Gerencias", acceso="interno", nuevo="admin",
                      texto_nuevo="Registrar gerencia",
                      qs=lambda r: buscar(visibles(r.user, Gerencia).annotate(n=Count("centros")).order_by("nombre"),
                                          r, ["nombre"]),
                      filtros=lambda r: [], fila=lambda g: [g.nombre, g.n], cols=["Gerencia", "Centros"],
                      acciones=acc_admin("gerencias")),
    "centros": dict(modulo="Centros", titulo="Centros", acceso="interno", nuevo="editor", texto_nuevo="Registrar centro",
                    qs=lambda r: filtrar(buscar(visibles(r.user, Centro).select_related("gerencia")
                                                .annotate(n=Count("equipos")).order_by("gerencia__nombre", "nombre"),
                                                r, ["nombre", "direccion", "observaciones", "gerencia__nombre"]),
                                         r, {"gerencia": "gerencia_id"}),
                    filtros=lambda r: [sel(r, "gerencia", "Gerencia", op_gerencias(r.user))],
                    fila=lambda c: [c.gerencia.nombre, c.nombre, c.direccion, c.geolocalizacion, c.observaciones, c.n],
                    cols=["Gerencia", "Centro", "Dirección", "Geolocalización",
                          "Observaciones / necesidades tecnológicas", "Equipos"], enlace=3, acciones=acc_admin("centros")),
    "categorias": dict(modulo="Categorías", titulo="Categorías de equipo", acceso="interno", nuevo="editor",
                       texto_nuevo="Crear categoría",
                       qs=lambda r: buscar(Categoria.objects.annotate(n=Count("equipos")).order_by("id"), r,
                                           ["nombre", "descripcion"]),
                       filtros=lambda r: [], fila=lambda c: [c.nombre, c.descripcion, c.n],
                       cols=["Categoría", "Descripción", "Equipos"], acciones=acc_admin("categorias")),
    "usuarios": dict(modulo="Usuarios", titulo="Usuarios", acceso="admin", nuevo="admin", texto_nuevo="Crear usuario",
                     qs=lambda r: filtrar(buscar(Usuario.objects.select_related("gerencia", "centro").order_by("username"), r,
                                                 ["username", "first_name", "last_name", "cargo"]),
                                          r, {"rol": "rol", "gerencia": "gerencia_id", "activo": "is_active"}),
                     filtros=lambda r: [sel(r, "rol", "Rol", Usuario.ROLES),
                                        sel(r, "gerencia", "Gerencia", op_gerencias(r.user)),
                                        sel(r, "activo", "Activo", [("1", "Sí"), ("0", "No")])],
                     fila=lambda u: [u.username, u.first_name, u.last_name, u.cargo, u.get_rol_display(),
                                     u.gerencia.nombre if u.gerencia else "", u.centro.nombre if u.centro else "",
                                     "Sí" if u.is_active else "No"],
                     cols=["Usuario", "Nombre", "Apellido", "Cargo", "Rol", "Gerencia", "Centro", "Activo"],
                     acciones=acc_usuario),
    "bitacora": dict(modulo="Bitácora", titulo="Bitácora de acciones", acceso="admin", nuevo=None,
                     qs=qs_bitacora,
                     filtros=lambda r: [sel(r, "usuario", "Usuario", [(u.pk, str(u)) for u in Usuario.objects.all()]),
                                        sel(r, "accion", "Acción", Bitacora.ACCIONES),
                                        sel(r, "modulo", "Módulo", [(m, m) for m in
                                                                    sorted({x["modulo"] for x in LISTAS.values()} | {"Sesión"})])
                                        ] + rango(r),
                     fila=lambda b: [fecha_txt(b.fecha), b.usuario_nombre, b.get_accion_display(), b.modulo, b.detalle],
                     cols=["Fecha", "Usuario", "Acción", "Módulo", "Detalle"], rapidos=True),
}


def _url(request, quitar=(), poner=None):
    """Querystring actual quitando/poniendo parámetros (y siempre sin 'page')."""
    p = request.GET.copy()
    p.pop("page", None)
    p.pop("ver", None)                  # "ver" solo sirve para abrir un detalle una vez
    for n in quitar:
        p.pop(n, None)
    for k, v in (poner or {}).items():
        p[k] = v
    cadena = p.urlencode()
    return "?" + cadena if cadena else "?"


class _SinParametro:
    """Copia de la petición sin un parámetro: sirve para contar las pastillas de estatus."""
    def __init__(self, request, parametro):
        self.GET = request.GET.copy()
        self.GET.pop(parametro, None)
        self.user = request.user


@login_required
def lista(request, clave):
    c = LISTAS[clave]
    exigir(request, c["acceso"])
    page = Paginator(c["qs"](request), 15).get_page(request.GET.get("page"))
    nuevos = set()                                         # soportes con aviso sin leer para este usuario
    abrir, ver = "", request.GET.get("ver", "")             # llegó desde una notificación: abre el detalle de ese soporte
    if clave == "soportes" and ver.isdigit() and visibles(request.user, Soporte).filter(pk=int(ver)).exists():
        abrir = reverse("soportes_detalle", args=[int(ver)])
    etiqueta_nuevo = "Nuevo" if request.user.puede_editar else "Novedad"
    if clave == "soportes" and request.user.recibe_notificaciones:
        nuevos = set(Notificacion.objects.filter(usuario=request.user, leida=False, soporte__isnull=False)
                     .values_list("soporte_id", flat=True))
    filas = []
    for o in page:
        celdas = c["fila"](o)
        if c.get("badge"):
            i, colores = c["badge"]
            celdas[i] = badge(celdas[i], colores)
        i = c.get("enlace")
        if i is not None and celdas[i]:
            celdas[i] = format_html('<a href="{}" target="_blank" rel="noopener">'
                                    '<i class="bi bi-geo-alt"></i> Abrir en Google Maps</a>', celdas[i])
        if o.pk in nuevos:
            celdas[0] = format_html('<span class="badge text-bg-danger me-1">{}</span>{}', etiqueta_nuevo, celdas[0])
        acciones = c["acciones"](request.user, o) if c.get("acciones") else []
        filas.append({"celdas": celdas, "acciones": acciones})

    # --- filtros activos como "chips" que se pueden quitar uno por uno
    filtros, q = c["filtros"](request), request.GET.get("q", "").strip()
    chips = [{"texto": f"Búsqueda: {q}", "quitar": _url(request, ["q"])}] if q else []
    for fl in filtros:
        if fl["valor"]:
            txt = ("/".join(reversed(fl["valor"].split("-"))) if fl["tipo"] == "date"
                   else {v: t for v, t, _ in fl["opciones"]}.get(fl["valor"], fl["valor"]))
            chips.append({"texto": f"{fl['label']}: {txt}", "quitar": _url(request, [fl["name"]])})

    # --- pastillas de estatus con su contador (respetan los demás filtros)
    pastillas, estatus = None, request.GET.get("estatus", "")
    if c.get("pastillas"):
        cuentas = dict(c["qs"](_SinParametro(request, "estatus")).order_by().values_list("estatus").annotate(n=Count("id")))
        pastillas = [{"texto": "Todos", "n": sum(cuentas.values()), "activo": not estatus,
                      "url": _url(request, ["estatus"])}]
        for v, t in c["pastillas"]:
            pastillas.append({"texto": t, "n": cuentas.get(v, 0), "activo": estatus == v,
                              "url": _url(request, poner={"estatus": v})})
            if estatus == v:
                chips.append({"texto": f"Estatus: {t}", "quitar": _url(request, ["estatus"])})

    # --- rangos de fecha rápidos
    rapidos = None
    if c.get("rapidos"):
        hoy = timezone.localdate()
        def rango_url(desde):
            return _url(request, poner={"desde": desde.isoformat(), "hasta": hoy.isoformat()})
        rapidos = [("Hoy", rango_url(hoy)), ("Últimos 7 días", rango_url(hoy - timedelta(days=6))),
                   ("Este mes", rango_url(hoy.replace(day=1)))]
        if clave == "soportes" and request.user.rol == Usuario.TECNICO:
            rapidos.insert(0, ("Asignados a mí", _url(request, poner={"tecnico": request.user.pk})))

    params = request.GET.copy()
    params.pop("page", None)
    params.pop("ver", None)
    return render(request, "lista.html", {
        "titulo": c["titulo"], "columnas": c["cols"], "filas": filas, "page": page, "total": page.paginator.count,
        "filtros": filtros, "q": q, "chips": chips, "pastillas": pastillas, "estatus": estatus, "rapidos": rapidos,
        "params": params.urlencode(), "excel_url": reverse(f"{clave}_excel"), "tiene_acciones": bool(c.get("acciones")),
        "nuevo_url": reverse(f"{clave}_nuevo") if c["nuevo"] else "", "texto_nuevo": c.get("texto_nuevo", ""),
        "puede_nuevo": bool(c["nuevo"]) and nivel_ok(request.user, c["nuevo"]),
        "refrescable": clave == "soportes", "abrir_detalle": abrir,
    })


@login_required
def exportar(request, clave):
    """Descarga SOLO lo que muestra la tabla (mismos filtros, mismas columnas), en todas sus páginas."""
    c = LISTAS[clave]
    exigir(request, c["acceso"])
    filas = [c["fila"](o) for o in c["qs"](request)]
    filtros = request.GET.urlencode()
    registrar(request.user, "EXPORTAR", c["modulo"],
              f"Descargó Excel con {len(filas)} fila(s)" + (f" · filtros: {filtros}" if filtros else ""))
    return export_xlsx(clave, c["titulo"], c["cols"], filas)


# ============================================================================
#  Crear / editar / eliminar (genérico)
# ============================================================================
def _marcar_leidas(user, soporte):
    """Al abrir un soporte, sus avisos pendientes para ese usuario quedan como leídos."""
    if user.recibe_notificaciones:
        Notificacion.objects.filter(usuario=user, soporte=soporte, leida=False).update(leida=True)


def despues_soporte(obj, request):
    """Garantiza que el soporte tenga técnico de la gerencia de su centro (y le avisa)."""
    u, gerencia = request.user, obj.centro.gerencia_id
    t = obj.tecnico
    if t is None and u.rol == Usuario.TECNICO and u.gerencia_id == gerencia:       # un técnico lo toma
        obj.tecnico = u
        obj.save(update_fields=["tecnico"])
        return ""
    if t is None or (t.rol == Usuario.TECNICO and t.gerencia_id != gerencia):
        obj.tecnico = None
        t = asignar_tecnico(obj)
        return f" · Técnico asignado: {t}" if t else " · Sin técnico disponible en la gerencia"
    return ""


def despues_usuario(obj, request):
    """Un técnico nuevo (o que cambia de gerencia) toma las solicitudes abiertas de su gerencia que no tenían técnico."""
    if obj.rol == Usuario.TECNICO and obj.is_active and obj.gerencia_id:
        n = asignar_pendientes(obj.gerencia_id)
        return f" · Se le asignaron {n} solicitud(es) abierta(s)" if n else ""
    return ""


CRUD = {
    "equipos": dict(form=f.EquipoForm, modelo=Equipo, singular="equipo", nuevo="editor", editar="admin",
                    eliminar="admin", campos=C_EQUIPO),
    "soportes": dict(form=f.SoporteForm, modelo=Soporte, singular="soporte", nuevo="editor", editar="editor",
                     eliminar="admin", campos=C_SOPORTE,
                     al_crear=lambda obj, r: setattr(obj, "tecnico", r.user if r.user.rol == Usuario.TECNICO else None),
                     despues=despues_soporte,
                     form_restringido=f.SoporteTecnicoForm,     # lo que ve un técnico al editar (no administrador)
                     ayuda_restringido="Como técnico puedes modificar el hallazgo, la solución, las recomendaciones "
                                       "y el estatus. Los demás datos están bloqueados.",
                     ayuda="La fecha del soporte se registra automáticamente al guardar."),
    "gerencias": dict(form=f.GerenciaForm, modelo=Gerencia, singular="gerencia", nuevo="admin", editar="admin",
                      eliminar="admin", campos=C_GERENCIA),
    "centros": dict(form=f.CentroForm, modelo=Centro, singular="centro", nuevo="editor", editar="admin",
                    eliminar="admin", campos=C_CENTRO),
    "categorias": dict(form=f.CategoriaForm, modelo=Categoria, singular="categoría", nuevo="editor", editar="admin",
                       eliminar="admin", campos=C_CATEGORIA),
    "usuarios": dict(form=f.UsuarioCrearForm, form_editar=f.UsuarioEditarForm, modelo=Usuario, singular="usuario",
                     nuevo="admin", editar="admin", eliminar="admin", campos=C_USUARIO, despues=despues_usuario),
}


def _form(Form, request, instance=None):
    """Instancia el formulario; si lo necesita, le pasa el usuario para acotar gerencias y centros."""
    kw = {"user": request.user} if getattr(Form, "usa_usuario", False) else {}
    if instance is not None:
        kw["instance"] = instance
    return Form(request.POST or None, **kw)


@login_required
def crear(request, clave):
    c = CRUD[clave]
    exigir(request, c["nuevo"])
    form = _form(c["form"], request)
    if request.method == "POST" and form.is_valid():
        if c.get("al_crear"):
            c["al_crear"](form.instance, request)
        obj = form.save()
        extra = c["despues"](obj, request) if c.get("despues") else ""
        registrar(request.user, "CREAR", LISTAS[clave]["modulo"], f"Registró: {obj}{extra}")
        messages.success(request, "Registro creado correctamente.")
        return redirect(clave)
    return render(request, "form.html", {"form": form, "titulo": f"Registrar {c['singular']}",
                                         "volver": reverse(clave), "ayuda": c.get("ayuda")})


@login_required
def editar(request, clave, pk):
    c = CRUD[clave]
    exigir(request, c["editar"])
    obj = get_object_or_404(visibles(request.user, c["modelo"]), pk=pk)
    if clave == "soportes":
        _marcar_leidas(request.user, obj)
    antes = valores(obj, c["campos"])              # foto ANTES de validar (el form modifica la instancia)
    restringido = c.get("form_restringido") and not request.user.es_admin
    Form = c["form_restringido"] if restringido else c.get("form_editar", c["form"])
    form = _form(Form, request, obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        extra = c["despues"](obj, request) if c.get("despues") else ""
        cambs = cambios(antes, valores(obj, c["campos"]))
        registrar(request.user, accion_de_edicion(cambs), LISTAS[clave]["modulo"],
                  f"{obj} — {describir(cambs) or 'sin cambios'}{extra}")
        if clave == "soportes":                                    # los solicitantes del centro se enteran del cambio
            avisar_cambios_soporte(request.user, obj, cambs)
        messages.success(request, "Cambios guardados.")
        return redirect(clave)
    return render(request, "form.html", {"form": form, "titulo": f"Editar {c['singular']}", "volver": reverse(clave),
                                         "ayuda": c["ayuda_restringido"] if restringido else c.get("ayuda")})


@login_required
def eliminar(request, clave, pk):
    c = CRUD[clave]
    exigir(request, c["eliminar"])
    obj = get_object_or_404(visibles(request.user, c["modelo"]), pk=pk)
    if clave == "usuarios" and obj.pk == request.user.pk:
        messages.error(request, "No puedes eliminar tu propio usuario.")
        return redirect(clave)
    if request.method == "POST":
        descripcion = str(obj)
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, "No se puede eliminar: tiene registros asociados "
                                    "(centros, equipos o soportes). Muévelos o elimínalos primero.")
            return redirect(clave)
        registrar(request.user, "ELIMINAR", LISTAS[clave]["modulo"], f"Eliminó: {descripcion}")
        messages.success(request, "Registro eliminado.")
        return redirect(clave)
    return render(request, "confirmar.html", {"objeto": obj, "volver": reverse(clave)})


@login_required
def equipo_mover(request, pk):
    """Mover entre centros y/o cambiar el estatus. El técnico solo dentro de su gerencia; el administrador, entre todas."""
    exigir(request, "editor")
    obj = get_object_or_404(visibles(request.user, Equipo), pk=pk)
    antes = valores(obj, C_EQUIPO)
    form = _form(f.MoverEquipoForm, request, obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        cambs = cambios(antes, valores(obj, C_EQUIPO))
        nota = form.cleaned_data["nota"].strip()
        detalle = f"{obj} — {describir(cambs) or 'sin cambios'}" + (f" · Nota: {nota}" if nota else "")
        registrar(request.user, accion_de_edicion(cambs), "Equipos", detalle)
        messages.success(request, "Equipo actualizado.")
        return redirect("equipos")
    return render(request, "form.html", {"form": form, "titulo": f"Mover / cambiar estatus · {obj}",
                                         "volver": reverse("equipos")})


@login_required
def soporte_detalle(request, pk):
    """Contenido del cuadro emergente con la información completa del soporte (solo de lo que el usuario puede ver)."""
    s = get_object_or_404(visibles(request.user, Soporte).select_related("centro__gerencia", "tecnico"), pk=pk)
    _marcar_leidas(request.user, s)
    items = [("Fecha", fecha_dia(s.fecha)), ("Gerencia", s.centro.gerencia.nombre), ("Centro", s.centro.nombre),
             ("Área", s.area), ("Motivo", s.motivo), ("Hallazgo", s.hallazgo), ("Solución", s.solucion),
             ("Recomendaciones", s.recomendaciones), ("Persona que solicitó el servicio", s.solicitante),
             ("Técnico", str(s.tecnico) if s.tecnico else ""), ("Estatus", s.get_estatus_display())]
    return render(request, "parciales/detalle.html", {"titulo": f"Soporte #{s.pk}", "items": items})


# ============================================================================
#  Rol Solicitante: sus activos, sus soportes y el formulario para solicitar uno
# ============================================================================
@login_required
def soporte_solicitar(request):
    """El solicitante pide un soporte para su centro: queda registrado como Pendiente."""
    exigir(request, "solicitante")
    u = request.user
    form = f.SolicitudSoporteForm(request.POST or None)      # el nombre del solicitante se escribe a mano
    if request.method == "POST" and form.is_valid():
        s = Soporte.objects.create(centro=u.centro, motivo=form.cleaned_data["motivo"],
                                   solicitante=form.cleaned_data["solicitante"], area=form.cleaned_data["area"],
                                   estatus="PENDIENTE")
        tecnico = asignar_tecnico(s)
        avisar_solicitud_nueva(s)                                  # Solo consulta se entera de toda solicitud nueva
        registrar(u, "CREAR", "Soportes", f"Solicitó: {s}" + (f" · Técnico asignado: {tecnico}" if tecnico
                                                              else " · Sin técnico disponible en la gerencia"))
        messages.success(request, "Solicitud enviada. Quedó registrada como pendiente.")
        return redirect("dashboard")
    return render(request, "form.html", {
        "form": form, "titulo": "Solicitar soporte", "volver": reverse("dashboard"), "boton": "Enviar solicitud",
        "ayuda": f"Tu solicitud quedará como pendiente para {u.centro} ({u.centro.gerencia}). "
                 "La fecha se registra automáticamente."})


def inicio_solicitante(request):
    u, g = request.user, request.GET
    activos = filtrar(buscar(visibles(u, Equipo).select_related("categoria"), request,
                             ["equipo_otro", "categoria__nombre", "marca", "modelo", "serial", "activo_fijo", "area"], "qa"),
                      request, {"ea": "estatus"}).order_by("categoria__nombre", "equipo_otro", "marca")
    soportes = fechas(filtrar(buscar(visibles(u, Soporte).select_related("tecnico"), request,
                                     ["motivo", "solicitante", "area", "tecnico__first_name", "tecnico__last_name"], "qs"),
                              request, {"es": "estatus", "ss": "solicitante"}), request, "fecha")
    pa = Paginator(activos, 10).get_page(g.get("pa"))
    ps = Paginator(soportes, 10).get_page(g.get("ps"))
    de_activos, de_soportes = ("qa", "ea"), ("qs", "es", "ss", "desde", "hasta")   # parámetros de cada tabla
    nuevos = set(Notificacion.objects.filter(usuario=u, leida=False, soporte__isnull=False).values_list("soporte_id", flat=True))
    marcar = lambda pk, txt: format_html('<span class="badge text-bg-danger me-1">Actualizado</span>{}', txt) if pk in nuevos else txt
    ver = g.get("ver", "")                                   # llega desde una notificación: abre el detalle de ese soporte
    abrir = reverse("soportes_detalle", args=[int(ver)]) if ver.isdigit() and visibles(u, Soporte).filter(pk=int(ver)).exists() else ""

    def tabla(pg, parametro, filas, ancla, propios, ajenos, **extra):
        """Datos de una tabla: página, filas, enlaces de paginación y barra de filtros. Cada formulario conserva los
        filtros de la otra tabla (campos ocultos) para no perderlos al filtrar."""
        return {"page": pg, "filas": filas, "ancla": ancla, "filtrado": any(g.get(n) for n in propios),
                "prev": _url(request, poner={parametro: pg.previous_page_number()}) if pg.has_previous() else "",
                "next": _url(request, poner={parametro: pg.next_page_number()}) if pg.has_next() else "",
                "ocultos": [(n, g[n]) for n in ajenos if g.get(n)],
                "limpiar": _url(request, propios + (parametro,)), **extra}

    return render(request, "solicitante.html", {
        "centro": u.centro, "abrir_detalle": abrir,
        "activos": tabla(pa, "pa", [[e.nombre_equipo, e.marca, e.modelo, e.serial, e.activo_fijo, e.area, e.cantidad,
                                     badge(e.get_estatus_display(), COLOR_EQ)] for e in pa],
                         "panelActivos", de_activos, de_soportes, form_id="filtrosActivos", q_name="qa",
                         q_valor=g.get("qa", ""), filtros=[sel(request, "ea", "Estatus", Equipo.ESTATUS)]),
        "soportes": tabla(ps, "ps", [{"pk": s.pk, "celdas": [
                              marcar(s.pk, fecha_dia(s.fecha)), s.area, s.motivo, s.solicitante,
                              (s.tecnico.get_full_name() or s.tecnico.username) if s.tecnico else "Por asignar",
                              badge(s.get_estatus_display(), COLOR_SOP)]} for s in ps],
                          "panelSoportes", de_soportes, de_activos, form_id="filtrosSoportes", q_name="qs",
                          q_valor=g.get("qs", ""),
                          filtros=[sel(request, "es", "Estatus", Soporte.ESTATUS),
                                   sel(request, "ss", "Solicitó", [(n, n) for n in nombres_solicitantes(u)])] + rango(request)),
    })


# ============================================================================
#  Dashboard
# ============================================================================
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


@login_required
def dashboard(request):
    u = request.user
    if u.es_solicitante:                       # el solicitante no ve gráficos: solo sus tablas
        return inicio_solicitante(request)
    sop, eq = visibles(u, Soporte), visibles(u, Equipo)
    s_cnt = dict(sop.order_by().values_list("estatus").annotate(n=Count("id")))
    e_cnt = dict(eq.order_by().values_list("estatus").annotate(n=Sum("cantidad")))
    hoy = timezone.localdate()
    meses, y, m = [], hoy.year, hoy.month
    for _ in range(6):
        meses.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    meses.reverse()
    desde = timezone.make_aware(datetime(meses[0][0], meses[0][1], 1))
    por_mes = {(r["mes"].year, r["mes"].month): r["n"] for r in
               sop.filter(fecha__gte=desde).annotate(mes=TruncMonth("fecha"))
               .order_by().values("mes").annotate(n=Count("id"))}
    por_gerencia = list(sop.order_by().values("centro__gerencia__nombre").annotate(n=Count("id")).order_by("-n")[:8])
    datos = {
        "soportes": {"labels": [t for _, t in Soporte.ESTATUS], "data": [s_cnt.get(v, 0) for v, _ in Soporte.ESTATUS],
                     "colors": ["#f59e0b", "#0ea5e9", "#10b981"]},
        "equipos": {"labels": [t for _, t in Equipo.ESTATUS], "data": [e_cnt.get(v, 0) or 0 for v, _ in Equipo.ESTATUS],
                    "colors": ["#10b981", "#ef4444", "#f59e0b", "#94a3b8"]},
        "gerencias": {"labels": [r["centro__gerencia__nombre"] for r in por_gerencia],
                      "data": [r["n"] for r in por_gerencia]},
        "meses": {"labels": [f"{MESES[mm - 1]} {yy}" for yy, mm in meses],
                  "data": [por_mes.get(k, 0) for k in meses]},
    }
    asignados, n_asignados, nuevos = None, 0, set()
    if u.rol == Usuario.TECNICO:                           # tabla de solicitudes asignadas al técnico
        abiertos = sop.filter(tecnico=u).exclude(estatus="RESUELTO")
        n_asignados = abiertos.count()
        asignados = list(abiertos.select_related("centro__gerencia").order_by("-fecha", "-id")[:8])
        nuevos = set(Notificacion.objects.filter(usuario=u, leida=False, soporte__isnull=False)
                     .values_list("soporte_id", flat=True))
    alcance = "Todas las gerencias" if u.ve_todo else (u.gerencia.nombre if u.gerencia_id else "Sin gerencia asignada")
    return render(request, "dashboard.html", {
        "datos": datos, "s_cnt": s_cnt, "total_soportes": sum(s_cnt.values()), "alcance": alcance,
        "total_equipos": sum(v or 0 for v in e_cnt.values()), "total_centros": visibles(u, Centro).count(),
        "recientes": sop.select_related("centro__gerencia")[:6],
        "puede_editar": u.puede_editar, "asignados": asignados, "n_asignados": n_asignados, "nuevos": nuevos,
    })


# ============================================================================
#  Notificaciones (campana de la barra superior)
# ============================================================================
@login_required
def notificaciones_resumen(request):
    """JSON que consulta la campana cada cierto tiempo: contador, lista ya renderizada y el último aviso."""
    exigir(request, "notificable")
    qs = Notificacion.objects.filter(usuario=request.user)
    ultimo = qs.order_by("-id").first()
    return JsonResponse({
        "no_leidas": qs.filter(leida=False).count(),
        "ultimo_id": ultimo.pk if ultimo else 0,
        "ultimo_mensaje": ultimo.mensaje if ultimo else "",
        "html": render_to_string("parciales/notificaciones.html", {"items": qs[:10]}, request),
    })


@login_required
def notificaciones_abrir(request, pk):
    """Marca el aviso como leído y lleva al soporte (el técnico a editarlo; el solicitante a ver su detalle)."""
    exigir(request, "notificable")
    n = get_object_or_404(Notificacion, pk=pk, usuario=request.user)
    if not n.leida:
        n.leida = True
        n.save(update_fields=["leida"])
    if n.soporte_id and visibles(request.user, Soporte).filter(pk=n.soporte_id).exists():
        if request.user.puede_editar:
            return redirect("soportes_editar", pk=n.soporte_id)
        if request.user.es_solicitante:
            return redirect(f"{reverse('dashboard')}?ver={n.soporte_id}")
        return redirect(f"{reverse('soportes')}?ver={n.soporte_id}")         # Solo consulta: lista con el detalle abierto
    return redirect("dashboard" if request.user.es_solicitante else "soportes")


@login_required
@require_POST
def notificaciones_leer_todas(request):
    exigir(request, "notificable")
    Notificacion.objects.filter(usuario=request.user, leida=False).update(leida=True)
    destino = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        destino = reverse("dashboard")
    return redirect(destino)
