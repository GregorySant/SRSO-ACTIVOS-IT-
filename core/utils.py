from django.core.exceptions import FieldDoesNotExist
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Bitacora, Notificacion, Soporte, Usuario


def registrar(usuario, accion, modulo, detalle=""):
    """Guarda una línea en la bitácora de acciones."""
    ok = usuario is not None and getattr(usuario, "pk", None)
    Bitacora.objects.create(usuario=usuario if ok else None,
                            usuario_nombre=str(usuario) if ok else "Sistema",
                            accion=accion, modulo=modulo, detalle=detalle[:2000])


def _txt(v, limite=70):
    if v is None or v == "":
        return "—"
    if v is True:
        return "Sí"
    if v is False:
        return "No"
    v = str(v).replace("\n", " ")
    return v if len(v) <= limite else v[:limite - 1] + "…"


def valores(obj, campos):
    """Foto legible de un objeto: {etiqueta: valor}. Sirve para comparar antes/después."""
    out = {}
    for nombre, etiqueta in campos:
        try:
            campo = obj._meta.get_field(nombre)
        except FieldDoesNotExist:
            campo = None
        v = getattr(obj, nombre)
        if campo is not None and campo.choices:
            v = getattr(obj, f"get_{nombre}_display")()
        out[etiqueta] = _txt(v)
    return out


def cambios(antes, despues):
    return {k: (antes.get(k), v) for k, v in despues.items() if antes.get(k) != v}


def describir(cambs):
    return "; ".join(f"{k}: {a} → {b}" for k, (a, b) in cambs.items())


def accion_de_edicion(cambs):
    if "Ubicación" in cambs:
        return "MOVER"
    if set(cambs) == {"Estatus"}:
        return "ESTATUS"
    return "EDITAR"


def export_xlsx(nombre, titulo, columnas, filas):
    """Genera un .xlsx con exactamente las columnas y filas recibidas."""
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    ws.append(list(columnas))
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0B1A2E")
        c.alignment = Alignment(vertical="center")
    anchos = [len(str(c)) for c in columnas]
    for fila in filas:
        fila = ["" if v is None else v for v in fila]
        ws.append(fila)
        for i, v in enumerate(fila):
            anchos[i] = max(anchos[i], min(len(str(v)), 60))
    for row in ws.iter_rows(min_row=2):          # evita que un texto que empiece con "=" se ejecute como fórmula
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.data_type = "s"
    for i, ancho in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(i)].width = ancho + 3
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{nombre}_{timezone.localdate():%Y%m%d}.xlsx"'
    wb.save(resp)
    return resp


# ============================================================================
#  Asignación automática de técnico y notificaciones
# ============================================================================
def tecnico_para(centro):
    """Técnico activo de la gerencia del centro con menos soportes abiertos (pendientes o en proceso)."""
    return (Usuario.objects.filter(rol=Usuario.TECNICO, is_active=True, gerencia_id=centro.gerencia_id)
            .annotate(abiertos=Count("soportes_atendidos",
                                     filter=Q(soportes_atendidos__estatus__in=["PENDIENTE", "PROCESO"])))
            .order_by("abiertos", "id").first())


def notificar(destinatarios, mensaje, soporte=None):
    Notificacion.objects.bulk_create([Notificacion(usuario=u, mensaje=mensaje[:255], soporte=soporte)
                                      for u in destinatarios])


def asignar_tecnico(soporte, avisar_sin_tecnico=True):
    """Asigna al soporte el técnico de su gerencia y le avisa. Si la gerencia no tiene técnico, avisa a los administradores."""
    if soporte.tecnico_id:
        return soporte.tecnico
    aviso = f"Solicitud #{soporte.pk} · {soporte.centro}: {soporte.motivo} (solicita {soporte.solicitante})"
    tecnico = tecnico_para(soporte.centro)
    if tecnico:
        soporte.tecnico = tecnico
        soporte.save(update_fields=["tecnico"])
        notificar([tecnico], aviso, soporte)
    elif avisar_sin_tecnico:
        notificar(Usuario.objects.filter(rol=Usuario.ADMIN, is_active=True),
                  f"Sin técnico disponible en {soporte.centro.gerencia}. {aviso}", soporte)
    return tecnico


def asignar_pendientes(gerencia_id):
    """Al crear/editar un técnico: toma las solicitudes abiertas de su gerencia que aún no tenían técnico."""
    n = 0
    abiertos = (Soporte.objects.filter(tecnico__isnull=True, centro__gerencia_id=gerencia_id)
                .exclude(estatus="RESUELTO").select_related("centro__gerencia"))
    for s in abiertos:
        if asignar_tecnico(s, avisar_sin_tecnico=False):
            n += 1
    return n


def usuarios_consulta():
    return Usuario.objects.filter(rol=Usuario.CONSULTA, is_active=True)


def avisar_solicitud_nueva(soporte):
    """Una solicitud nueva: la reciben los usuarios de Solo consulta (ven todas las gerencias)."""
    tecnico = f"Técnico asignado: {soporte.tecnico}" if soporte.tecnico_id else "Sin técnico asignado"
    notificar(usuarios_consulta(),
              f"Nueva solicitud #{soporte.pk} · {soporte.centro} ({soporte.centro.gerencia}): {soporte.motivo} "
              f"(solicita {soporte.solicitante}) · {tecnico}", soporte)


def avisar_cambios_soporte(actor, soporte, cambs):
    """Un técnico o administrador modificó el soporte: avisa a los solicitantes del centro y a Solo consulta."""
    if not cambs:
        return
    largos = {"Hallazgo": "Hallazgo actualizado", "Solución": "Solución actualizada",
              "Recomendaciones": "Recomendaciones actualizadas"}           # textos largos: solo se indica que cambiaron
    partes = "; ".join(largos.get(k, f"{k}: {a} → {b}") for k, (a, b) in cambs.items())
    quien = actor.get_full_name() or actor.username
    solicitantes = Usuario.objects.filter(rol=Usuario.SOLICITANTE, is_active=True, centro_id=soporte.centro_id)
    notificar(solicitantes, f"Soporte #{soporte.pk} ({soporte.motivo}) actualizado por {quien}: {partes}", soporte)
    notificar(usuarios_consulta(), f"Soporte #{soporte.pk} · {soporte.centro} ({soporte.motivo}) actualizado por {quien}: {partes}", soporte)
