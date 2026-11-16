import re
from urllib.parse import urlparse

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password

from .models import Categoria, Centro, Equipo, Gerencia, Soporte, Usuario


class BS:
    """Aplica clases de Bootstrap a todos los campos."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            w = campo.widget
            clase = ("form-check-input" if isinstance(w, forms.CheckboxInput)
                     else "form-select" if isinstance(w, forms.Select) else "form-control")
            w.attrs["class"] = f"{w.attrs.get('class', '')} {clase}".strip()


class CentroSelect(forms.Select):
    """Select de centros que guarda la gerencia de cada opción (para filtrar por JS)."""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opt = super().create_option(name, value, label, selected, index, subindex, attrs)
        inst = getattr(value, "instance", None)
        if inst is not None:
            opt["attrs"]["data-gerencia"] = inst.gerencia_id
        return opt


class GerenciaForm(BS, forms.ModelForm):
    class Meta:
        model = Gerencia
        fields = ["nombre"]


class CentroForm(BS, forms.ModelForm):
    class Meta:
        model = Centro
        fields = ["gerencia", "nombre", "direccion", "geolocalizacion", "observaciones"]
        widgets = {"observaciones": forms.Textarea(attrs={"rows": 3}),
                   "geolocalizacion": forms.URLInput(attrs={"placeholder": "https://maps.app.goo.gl/..."})}
        help_texts = {"geolocalizacion": "En Google Maps busca el lugar, pulsa «Compartir» y pega aquí el enlace copiado."}

    usa_usuario = True

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and not user.ve_todo:
            self.fields["gerencia"].queryset = (Gerencia.objects.filter(pk=user.gerencia_id) if user.gerencia_id
                                                else Gerencia.objects.none())

    def clean_geolocalizacion(self):
        url = (self.cleaned_data.get("geolocalizacion") or "").strip()
        if url:
            p = urlparse(url)
            host, ruta = (p.hostname or "").lower(), p.path
            es_google = (host == "maps.app.goo.gl"
                         or (host == "goo.gl" and ruta.startswith("/maps"))
                         or re.fullmatch(r"maps\.google\.(com?\.)?[a-z]{2,3}", host)
                         or (re.fullmatch(r"(www\.)?google\.(com?\.)?[a-z]{2,3}", host) and ruta.startswith("/maps")))
            if not es_google:
                raise forms.ValidationError("Pega un enlace de Google Maps (por ejemplo "
                                            "https://maps.app.goo.gl/... o https://www.google.com/maps/...).")
        return url


class CategoriaForm(BS, forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre", "descripcion"]


class UbicacionForm(BS, forms.ModelForm):
    """Base: Gerencia (solo para filtrar) + Centro de esa gerencia."""
    gerencia = forms.ModelChoiceField(Gerencia.objects.all(), label="Gerencia", empty_label="Seleccione...")
    usa_usuario = True        # las vistas le pasan el usuario para acotar las gerencias y centros permitidos

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        centros = Centro.objects.select_related("gerencia")
        if user is not None and not user.ve_todo:          # un técnico solo trabaja dentro de su gerencia
            self.fields["gerencia"].queryset = (Gerencia.objects.filter(pk=user.gerencia_id) if user.gerencia_id
                                                else Gerencia.objects.none())
            centros = centros.filter(gerencia_id=user.gerencia_id) if user.gerencia_id else centros.none()
        self.fields["centro"].queryset = centros
        self.fields["centro"].empty_label = "Seleccione..."
        if self.instance.pk:
            self.fields["gerencia"].initial = self.instance.centro.gerencia_id

    def clean(self):
        d = super().clean()
        g, c = d.get("gerencia"), d.get("centro")
        if g and c and c.gerencia_id != g.pk:
            self.add_error("centro", "El centro no pertenece a la gerencia seleccionada.")
        return d


class EquipoForm(UbicacionForm):
    tipo = forms.ChoiceField(label="Equipo")
    field_order = ["tipo", "equipo_otro", "marca", "modelo", "serial", "activo_fijo",
                   "gerencia", "centro", "area", "cantidad", "estatus"]

    class Meta:
        model = Equipo
        fields = ["equipo_otro", "marca", "modelo", "serial", "activo_fijo", "centro", "area", "cantidad", "estatus"]
        widgets = {"centro": CentroSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].choices = ([("", "Seleccione...")]
                                       + [(str(c.pk), c.nombre) for c in Categoria.objects.all()]
                                       + [("OTROS", "OTROS (escribir)")])
        if self.instance.pk:
            self.fields["tipo"].initial = str(self.instance.categoria_id) if self.instance.categoria_id else "OTROS"

    def clean(self):
        d = super().clean()
        tipo = d.get("tipo")
        if tipo == "OTROS":
            if not (d.get("equipo_otro") or "").strip():
                self.add_error("equipo_otro", "Escribe el nombre del equipo.")
            self.instance.categoria = None
        elif tipo:
            self.instance.categoria = Categoria.objects.filter(pk=tipo).first()
            d["equipo_otro"] = ""
        for campo, nombre in (("activo_fijo", "activo fijo"), ("serial", "serial")):
            v = (d.get(campo) or "").strip()
            if v and Equipo.objects.filter(**{campo: v}).exclude(pk=self.instance.pk).exists():
                self.add_error(campo, f"Ya existe un equipo con este {nombre}.")
        return d


class MoverEquipoForm(UbicacionForm):
    nota = forms.CharField(label="Nota (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    field_order = ["gerencia", "centro", "estatus", "nota"]

    class Meta:
        model = Equipo
        fields = ["centro", "estatus"]
        widgets = {"centro": CentroSelect}


class SoporteForm(UbicacionForm):
    field_order = ["gerencia", "centro", "area", "motivo", "hallazgo", "solucion", "recomendaciones",
                   "solicitante", "estatus"]

    class Meta:
        model = Soporte
        fields = ["centro", "area", "motivo", "hallazgo", "solucion", "recomendaciones", "solicitante", "estatus"]
        widgets = {"centro": CentroSelect,
                   "hallazgo": forms.Textarea(attrs={"rows": 3}),
                   "solucion": forms.Textarea(attrs={"rows": 3}),
                   "recomendaciones": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:          # al crear son obligatorios; una solicitud recién llegada los trae vacíos
            self.fields["area"].required = True
            self.fields["hallazgo"].required = True


class SoporteTecnicoForm(SoporteForm):
    """Edición por un técnico: hallazgo, solución, recomendaciones y estatus. Gerencia, centro, área, motivo y
    solicitante quedan bloqueados en el servidor (un campo 'disabled' ignora lo que llegue por POST y conserva
    el valor guardado)."""
    EDITABLES = ("hallazgo", "solucion", "recomendaciones", "estatus")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre, campo in self.fields.items():
            if nombre not in self.EDITABLES:
                campo.disabled = True
                campo.required = False      # evita bloquear soportes antiguos que tengan algún dato vacío


class SolicitudSoporteForm(BS, forms.Form):
    """Formulario del rol Solicitante: motivo, nombre de quien solicita y área."""
    motivo = forms.CharField(label="Motivo", max_length=200, widget=forms.Textarea(attrs={"rows": 3}))
    solicitante = forms.CharField(label="Nombre del solicitante", max_length=150)
    area = forms.CharField(label="Área", max_length=100)


class RolUbicacionMixin:
    """Técnico y Solicitante necesitan gerencia; el Solicitante, además, un centro de esa gerencia."""
    def clean(self):
        d = super().clean()
        rol, g, c = d.get("rol"), d.get("gerencia"), d.get("centro")
        if rol in (Usuario.TECNICO, Usuario.SOLICITANTE) and not g:
            self.add_error("gerencia", "Este rol necesita una gerencia asignada.")
        if rol == Usuario.SOLICITANTE and not c:
            self.add_error("centro", "El solicitante necesita un centro asignado.")
        if g and c and c.gerencia_id != g.pk:
            self.add_error("centro", "El centro no pertenece a la gerencia seleccionada.")
        if rol != Usuario.SOLICITANTE:
            d["centro"] = None
        return d


class UsuarioCrearForm(BS, RolUbicacionMixin, UserCreationForm):
    class Meta:
        model = Usuario
        fields = ("username", "first_name", "last_name", "cargo", "rol", "gerencia", "centro")
        widgets = {"centro": CentroSelect}
        help_texts = {"centro": "Solo para el rol Solicitante."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario"
        for n, etiqueta in (("first_name", "Nombre"), ("last_name", "Apellido")):
            self.fields[n].label = etiqueta
            self.fields[n].required = True
        self.fields["gerencia"].empty_label = "Sin gerencia"
        self.fields["centro"].empty_label = "Sin centro"


class UsuarioEditarForm(BS, RolUbicacionMixin, forms.ModelForm):
    nueva_password = forms.CharField(label="Nueva contraseña (opcional)", required=False,
                                     widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = Usuario
        fields = ("username", "first_name", "last_name", "cargo", "rol", "gerencia", "centro", "is_active")
        widgets = {"centro": CentroSelect}
        help_texts = {"centro": "Solo para el rol Solicitante."}
        labels = {"username": "Usuario", "first_name": "Nombre", "last_name": "Apellido", "is_active": "Activo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gerencia"].empty_label = "Sin gerencia"
        self.fields["centro"].empty_label = "Sin centro"

    def clean_nueva_password(self):
        pw = self.cleaned_data.get("nueva_password")
        if pw:
            validate_password(pw, self.instance)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("nueva_password"):
            user.set_password(self.cleaned_data["nueva_password"])
        if commit:
            user.save()
        return user
