import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0003_geolocalizacion_y_area_soporte")]
    operations = [
        migrations.AlterField("usuario", "rol", models.CharField(
            choices=[("ADMIN", "Administrador"), ("TECNICO", "Técnico"), ("CONSULTA", "Solo consulta"),
                     ("SOLICITANTE", "Solicitante")], default="CONSULTA", max_length=15, verbose_name="Rol")),
        migrations.AddField("usuario", "centro", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="core.centro", verbose_name="Centro")),
        migrations.RenameField("soporte", "recibido_por", "solicitante"),
        migrations.AlterField("soporte", "solicitante", models.CharField(max_length=150, verbose_name="Persona que solicitó el servicio")),
        migrations.AlterField("soporte", "hallazgo", models.TextField(blank=True, verbose_name="Hallazgo")),
    ]
