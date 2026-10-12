from .base import *  # noqa: F403
from .base import BASE_DIR, env

SECRET_KEY = "test-secret-key-solo-para-pruebas"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {
    "default": env.db(
        "TEST_DATABASE_URL",
        default=env("DATABASE_URL", default="postgres://postgres:postgres@localhost:5432/crecenta"),
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
MEDIA_ROOT = BASE_DIR / ".test-media"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

AI_PROVIDER = "fake"
