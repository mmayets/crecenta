from pathlib import Path

from .base import *  # noqa: F403
from .base import BASE_DIR, STORAGES, env

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# ------------------------------------------------------------------ publicación bajo /crecenta
# La app vive en https://gtsst.uapa.edu.do/crecenta/ detrás de un proxy que quita el prefijo.
# FORCE_SCRIPT_NAME hace que todas las direcciones generadas (reverse, {% url %}, estáticos,
# redirecciones) lo lleven. Cada valor se puede cambiar con su variable o en la tabla parameters.
FORCE_SCRIPT_NAME = env("FORCE_SCRIPT_NAME", default="/crecenta").rstrip("/") or None
_PREFIX = FORCE_SCRIPT_NAME or ""
STATIC_URL = env("STATIC_URL", default=f"{_PREFIX}/static/")
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = env("MEDIA_URL", default=f"{_PREFIX}/media/")
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS", default=["https://gtsst.uapa.edu.do"]
)
# Las cookies quedan dentro de /crecenta/ y con nombre propio, para no chocar con otras
# aplicaciones Django publicadas en el mismo dominio.
SESSION_COOKIE_NAME = "crecenta_sessionid"
CSRF_COOKIE_NAME = "crecenta_csrftoken"
SESSION_COOKIE_PATH = f"{_PREFIX}/"
CSRF_COOKIE_PATH = f"{_PREFIX}/"

# ------------------------------------------------------------------ HTTPS y cookies
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
# La comprobación de salud del proxy no se redirige a HTTPS (con o sin el prefijo).
SECURE_REDIRECT_EXEMPT = [rf"^{_PREFIX.lstrip('/')}/?salud/$"]
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"

# ------------------------------------------------------------------ archivos
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Almacenamiento S3 compatible para comprobantes (opcional). Los archivos nunca son públicos:
# se sirven a través de una vista autenticada.
if env("AWS_STORAGE_BUCKET_NAME", default=""):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
            "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=None),
            "region_name": env("AWS_S3_REGION_NAME", default=None),
            "default_acl": "private",
            "querystring_auth": True,
            "file_overwrite": False,
        },
    }

ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="mandatory")
