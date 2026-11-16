from django.db import migrations

INICIALES = ["CPU", "UPS", "IMPRESORA", "LAPTOP", "TECLADO", "MOUSE", "MOUSEPAD", "USB", "MONITOR"]


def crear(apps, schema_editor):
    Categoria = apps.get_model("core", "Categoria")
    for nombre in INICIALES:
        Categoria.objects.get_or_create(nombre=nombre)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
