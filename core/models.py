from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models


class Gerencia(models.Model):
    nombre = models.CharField("Gerencia", max_length=120, unique=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Centro(models.Model):
    gerencia = models.ForeignKey(Gerencia, on_delete=models.PROTECT, related_name="centros", verbose_name="Gerencia")
    nombre = models.CharField("Centro", max_length=150)
    direccion = models.CharField("Dirección", max_length=255)
    geolocalizacion = models.URLField("Geolocalización (enlace de Google Maps)", max_length=500, blank=True)
    observaciones = models.TextField("Observaciones / necesidades tecnológicas", blank=True)

    class Meta:
        ordering = ["gerencia__nombre", "nombre"]
        constraints = [models.UniqueConstraint(fields=["gerencia", "nombre"], name="centro_unico_por_gerencia")]

    def __str__(self):
        return self.nombre

    @property
    def ubicacion(self):
        return f"{self.gerencia.nombre} / {self.nombre}"



class Usuario(AbstractUser):
    ADMIN, TECNICO, CONSULTA, SOLICITANTE = "ADMIN", "TECNICO", "CONSULTA", "SOLICITANTE"
    ROLES = [(ADMIN, "Administrador"), (TECNICO, "Técnico"), (CONSULTA, "Solo consulta"), (SOLICITANTE, "Solicitante")]

    cargo = models.CharField("Cargo", max_length=100, blank=True)
    rol = models.CharField("Rol", max_length=15, choices=ROLES, default=CONSULTA)
    gerencia = models.ForeignKey(Gerencia, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Gerencia")
    centro = models.ForeignKey(Centro, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Centro")

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.rol = self.ADMIN
        super().save(*args, **kwargs)

    @property
    def es_admin(self):
        return self.is_superuser or self.rol == self.ADMIN

    @property
    def puede_editar(self):
        return self.es_admin or self.rol == self.TECNICO

    @property
    def recibe_notificaciones(self):
        """Técnico y administrador (asignaciones), solicitante (cambios en sus soportes) y Solo consulta (solicitudes y cambios)."""
        return self.puede_editar or self.es_solicitante or self.rol == self.CONSULTA

    @property
    def es_solicitante(self):
        return self.rol == self.SOLICITANTE

    @property
    def ve_todo(self):
        """Administrador y Solo consulta ven todas las gerencias; el resto, solo lo que tiene asignado."""
        return self.es_admin or self.rol == self.CONSULTA

    def __str__(self):
        nombre = self.get_full_name()
        return f"{nombre} ({self.username})" if nombre else self.username


class Categoria(models.Model):
    nombre = models.CharField("Categoría", max_length=60, unique=True)
    descripcion = models.CharField("Descripción", max_length=200, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.nombre


class Equipo(models.Model):
    ESTATUS = [("OPERATIVO", "Operativo"), ("DANADO", "Dañado"),
               ("REPARACION", "En reparación"), ("DESINCORPORADO", "Desincorporado")]

    categoria = models.ForeignKey(Categoria, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="equipos", verbose_name="Equipo")
    equipo_otro = models.CharField("Especifique el equipo", max_length=100, blank=True)
    marca = models.CharField("Marca", max_length=80)
    modelo = models.CharField("Modelo", max_length=80)
    serial = models.CharField("Serial", max_length=100, blank=True)
    activo_fijo = models.CharField("Activo fijo", max_length=60, blank=True)
    centro = models.ForeignKey(Centro, on_delete=models.PROTECT, related_name="equipos", verbose_name="Centro")
    area = models.CharField("Área", max_length=100)
    cantidad = models.PositiveIntegerField("Cantidad", default=1, validators=[MinValueValidator(1)])
    estatus = models.CharField("Estatus del equipo", max_length=15, choices=ESTATUS, default="OPERATIVO")
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-actualizado"]

    @property
    def nombre_equipo(self):
        return self.categoria.nombre if self.categoria_id else self.equipo_otro

    @property
    def ubicacion(self):
        return self.centro.ubicacion

    def __str__(self):
        extra = f" · S/N {self.serial}" if self.serial else ""
        return f"{self.nombre_equipo} {self.marca} {self.modelo}{extra}"


class Soporte(models.Model):
    ESTATUS = [("PENDIENTE", "Pendiente"), ("PROCESO", "En proceso"), ("RESUELTO", "Resuelto")]

    centro = models.ForeignKey(Centro, on_delete=models.PROTECT, related_name="soportes", verbose_name="Centro")
    area = models.CharField("Área", max_length=100, blank=True)
    motivo = models.CharField("Motivo", max_length=200)
    hallazgo = models.TextField("Hallazgo", blank=True)
    solucion = models.TextField("Solución", blank=True)
    recomendaciones = models.TextField("Recomendaciones", blank=True)
    solicitante = models.CharField("Persona que solicitó el servicio", max_length=150)
    estatus = models.CharField("Estatus del soporte", max_length=10, choices=ESTATUS, default="PENDIENTE")
    fecha = models.DateTimeField("Fecha", auto_now_add=True)
    tecnico = models.ForeignKey(Usuario, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="soportes_atendidos", verbose_name="Técnico")

    class Meta:
        ordering = ["-fecha"]

    @property
    def ubicacion(self):
        return self.centro.ubicacion

    def __str__(self):
        return f"Soporte #{self.pk} · {self.centro} · {self.motivo}"


class Bitacora(models.Model):
    ACCIONES = [("CREAR", "Creó"), ("EDITAR", "Editó"), ("ELIMINAR", "Eliminó"), ("ESTATUS", "Cambió estatus"),
                ("MOVER", "Movió"), ("EXPORTAR", "Exportó"), ("LOGIN", "Inició sesión"), ("LOGOUT", "Cerró sesión")]

    usuario = models.ForeignKey(Usuario, null=True, blank=True, on_delete=models.SET_NULL, related_name="acciones")
    usuario_nombre = models.CharField(max_length=200)   # se conserva aunque se elimine el usuario
    accion = models.CharField(max_length=10, choices=ACCIONES)
    modulo = models.CharField(max_length=40)
    detalle = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y %H:%M} {self.usuario_nombre} {self.accion}"


class Notificacion(models.Model):
    """Aviso para un usuario (p. ej. el técnico al que se le asignó una solicitud de soporte)."""
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name="notificaciones")
    mensaje = models.CharField(max_length=255)
    soporte = models.ForeignKey(Soporte, null=True, blank=True, on_delete=models.CASCADE, related_name="notificaciones")
    leida = models.BooleanField(default=False)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.usuario} · {self.mensaje}"
