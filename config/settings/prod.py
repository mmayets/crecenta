from .base import *  # noqa: F403
from .base import STORAGES, env

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# ------------------------------------------------------------------ HTTPS y cookies
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^salud/$"]
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
