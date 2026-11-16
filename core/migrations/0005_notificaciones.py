import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0004_solicitante_y_segmentacion")]
    operations = [
        migrations.CreateModel(
            name="Notificacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mensaje", models.CharField(max_length=255)),
                ("leida", models.BooleanField(default=False)),
                ("fecha", models.DateTimeField(auto_now_add=True)),
                ("soporte", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                              related_name="notificaciones", to="core.soporte")),
                ("usuario", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name="notificaciones", to="core.usuario")),
            ],
            options={"ordering": ["-fecha", "-id"]},
        ),
    ]
