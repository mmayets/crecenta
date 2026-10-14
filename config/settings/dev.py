from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)

# WhiteNoise sirve los estáticos también en runserver, con «Cache-Control: max-age=0»: el
# navegador revalida cada vez y toma el CSS nuevo con un refresco normal.
INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]  # noqa: F405
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-inseguro-no-usar-en-produccion")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"])

# Sin Redis (p. ej. en PyCharm sobre Windows): caché en memoria y tareas de Celery en el mismo
# proceso. Basta con dejar REDIS_URL vacío en .env (ver docs/pycharm.md).
if not env("REDIS_URL", default="redis://localhost:6379/0"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_BROKER_URL = "memory://localhost/"
    CELERY_RESULT_BACKEND = "cache+memory://"
