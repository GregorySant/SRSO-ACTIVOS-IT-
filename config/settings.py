import os
import uuid
from pathlib import Path

from django.contrib.messages import constants as message_constants

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Seguridad: en producción define estas variables de entorno -------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-cambia-esta-clave-en-produccion")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.SesionPorArranqueMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "core.context.globales",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "core.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Santo_Domingo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sesiones -----------------------------------------------------------------
# La sesión vence al cerrar el navegador y, si CERRAR_SESION_AL_REINICIAR está activo, también cuando
# se detiene y se vuelve a iniciar el servidor (ARRANQUE_ID cambia en cada inicio; el autoreload de
# runserver lo conserva para no cerrarte la sesión al guardar un archivo).
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
ARRANQUE_ID = os.environ.setdefault("MESA_AYUDA_ARRANQUE", uuid.uuid4().hex)
CERRAR_SESION_AL_REINICIAR = os.environ.get("DJANGO_CERRAR_SESION_AL_REINICIAR", "1" if DEBUG else "0") == "1"
FORMS_URLFIELD_ASSUME_HTTPS = True

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# --- Personalización ---------------------------------------------------------
NOMBRE_APP = "Soportes y Activos"
LOGO = "img/SRSO.jpeg"         # ruta dentro de /static/. Cambia aquí si tu logo es .png
