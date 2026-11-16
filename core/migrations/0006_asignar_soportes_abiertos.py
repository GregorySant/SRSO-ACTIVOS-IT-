from django.db import migrations


def asignar(apps, schema_editor):
    """Asigna técnico (de la gerencia del centro, el de menor carga) a los soportes abiertos que no lo tienen."""
    Soporte, Usuario, Notificacion = (apps.get_model("core", n) for n in ("Soporte", "Usuario", "Notificacion"))
    abiertos = ["PENDIENTE", "PROCESO"]
    for s in Soporte.objects.filter(tecnico__isnull=True).exclude(estatus="RESUELTO").select_related("centro"):
        candidatos = list(Usuario.objects.filter(rol="TECNICO", is_active=True, gerencia_id=s.centro.gerencia_id))
        if not candidatos:
            continue
        carga = {t.pk: Soporte.objects.filter(tecnico=t, estatus__in=abiertos).count() for t in candidatos}
        t = min(candidatos, key=lambda x: (carga[x.pk], x.pk))
        s.tecnico = t
        s.save(update_fields=["tecnico"])
        Notificacion.objects.create(usuario=t, soporte=s, mensaje=(
            f"Solicitud #{s.pk} · {s.centro.nombre}: {s.motivo} (solicita {s.solicitante})")[:255])


class Migration(migrations.Migration):
    dependencies = [("core", "0005_notificaciones")]
    operations = [migrations.RunPython(asignar, migrations.RunPython.noop)]
