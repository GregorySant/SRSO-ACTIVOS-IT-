from django.db import migrations, models


def coordenadas_a_enlace(apps, schema_editor):
    """Conserva la ubicación de los centros ya registrados convirtiéndola en un enlace de Google Maps."""
    Centro = apps.get_model("core", "Centro")
    for c in Centro.objects.exclude(latitud=None).exclude(longitud=None):
        c.geolocalizacion = f"https://www.google.com/maps?q={c.latitud},{c.longitud}"
        c.save(update_fields=["geolocalizacion"])


class Migration(migrations.Migration):
    dependencies = [("core", "0002_categorias_iniciales")]
    operations = [
        migrations.AddField("centro", "geolocalizacion", models.URLField(
            blank=True, max_length=500, verbose_name="Geolocalización (enlace de Google Maps)")),
        migrations.AddField("soporte", "area", models.CharField(blank=True, max_length=100, verbose_name="Área")),
        migrations.RunPython(coordenadas_a_enlace, migrations.RunPython.noop),
        migrations.RemoveField("centro", "latitud"),
        migrations.RemoveField("centro", "longitud"),
    ]
