"""Configuración común a todos los entornos.

La conexión a la base de datos sale de `config/db.py` y el resto de los valores por entorno de la
tabla `parameters` (ver `config/parameters.py`). Una variable de entorno, si existe, gana sobre
ambos (útil en CI; ver `.env.example`).
"""

from pathlib import Path

import environ
from celery.schedules import crontab

from config.parameters import load_parameters

try:
    from config import db as local_db
except ImportError:  # sin config/db.py (p. ej. en CI) la conexión llega por DATABASE_URL
    local_db = None

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

# ------------------------------------------------------------------ base de datos
if env("DATABASE_URL", default="") or local_db is None:
    DATABASES = {
        "default": env.db(
            "DATABASE_URL", default="postgres://crecenta:crecenta@localhost:5432/crecenta"
        ),
    }
else:
    DATABASES = {"default": dict(local_db.DATABASE)}
POSTGRES_ADMIN_URL = env("POSTGRES_ADMIN_URL", default=getattr(local_db, "POSTGRES_ADMIN_URL", ""))

# Los tests no dependen de los parámetros de la base de desarrollo.
if not env("DJANGO_SETTINGS_MODULE", default="").endswith(".test"):
    load_parameters(DATABASES["default"])

DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# ------------------------------------------------------------------ aplicaciones
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
]
THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
]
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.workspaces",
    "apps.ledger",
    "apps.personal",
    "apps.ai",
    "apps.planning",
    "apps.alerts",
    "apps.receipts",
    "apps.onboarding",
    "apps.reports",
    "apps.pwa",
    "apps.business",
    "apps.backoffice",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.backoffice.middleware.AuditMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.workspaces.context_processors.workspaces",
                "apps.accounts.context_processors.push",
            ],
        },
    },
]

# ------------------------------------------------------------------ caché (rate limiting, sesiones)
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# ------------------------------------------------------------------ autenticación
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "home"
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"

# allauth: acceso por correo + contraseña; Google opcional (se activa con credenciales).
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="optional")
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_RATE_LIMITS = {"login_failed": "10/m/ip,5/5m/key"}

GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")
SOCIALACCOUNT_PROVIDERS: dict = {}
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS["google"] = {
        "APPS": [{"client_id": GOOGLE_CLIENT_ID, "secret": GOOGLE_CLIENT_SECRET, "key": ""}],
        "SCOPE": ["profile", "email"],
        # Google verifica el correo: quien ya tiene cuenta con ese correo entra a la misma.
        "EMAIL_AUTHENTICATION": True,
    }
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_ENABLED_GOOGLE = bool(SOCIALACCOUNT_PROVIDERS)

# ------------------------------------------------------------------ idioma y zona horaria
LANGUAGE_CODE = "es"
LANGUAGES = [("es", "Español")]
TIME_ZONE = env("TIME_ZONE", default="America/Santo_Domingo")
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

# Ruta del panel de administración (en producción conviene no usar la predeterminada).
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")
# Límites de uso por persona: (cantidad, ventana en segundos).
UPLOAD_RATE_LIMITS = [(60, 3600)]
SYNC_RATE_LIMITS = [(120, 60)]

# Notificaciones push (Web Push con VAPID). Las claves se generan con `manage.py generar_vapid`.
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", default="")
VAPID_SUBJECT = env("VAPID_SUBJECT", default="mailto:soporte@crecenta.app")

# Versión de la app (también invalida la caché del service worker).
APP_VERSION = env("APP_VERSION", default="1")

# Moneda por defecto de los espacios nuevos (DOP o USD).
DEFAULT_CURRENCY = env("DEFAULT_CURRENCY", default="DOP")

# ------------------------------------------------------------------ archivos
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Comprobantes: tamaño máximo y tipos aceptados (ver docs/decisiones.md).
RECEIPT_MAX_BYTES = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = RECEIPT_MAX_BYTES + 1024 * 1024

# ------------------------------------------------------------------ correo
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Crecenta <no-responder@crecenta.app>")

# ------------------------------------------------------------------ Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_TIME_LIMIT = 120
CELERY_BEAT_SCHEDULE: dict = {
    "alertas-diarias": {
        "task": "alerts.evaluate_all",
        "schedule": crontab(hour=7, minute=0),
    },
    # Antes de las alertas: así ya cuentan con el sueldo y los pagos fijos del día.
    "registro-automatico": {
        "task": "personal.auto_record_all",
        "schedule": crontab(hour=6, minute=30),
    },
}

# ------------------------------------------------------------------ IA
AI_PROVIDER = env("AI_PROVIDER", default="fake")  # gemini | openai | fake
AI_DEBUG_LOG = env.bool("AI_DEBUG_LOG", default=False)  # guarda prompts y respuestas (solo depurar)
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
GEMINI_MODEL = env("GEMINI_MODEL", default="gemini-2.5-flash")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_MODEL = env("OPENAI_MODEL", default="gpt-4.1-mini")
OPENAI_TRANSCRIBE_MODEL = env("OPENAI_TRANSCRIBE_MODEL", default="gpt-4o-mini-transcribe")
# Límite de llamadas de IA por usuario: (cantidad, ventana en segundos).
AI_RATE_LIMITS = [
    (env.int("AI_LIMIT_PER_HOUR", default=30), 3600),
    (env.int("AI_LIMIT_PER_DAY", default=200), 86400),
]

# ------------------------------------------------------------------ seguridad común
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # htmx lee el token desde la cookie/meta
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
