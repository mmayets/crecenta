# Despliegue en https://gtsst.uapa.edu.do/crecenta/

Crecenta se publica bajo el prefijo `/crecenta/` de un dominio compartido con otras aplicaciones.
Un proxy (nginx o Apache) recibe `https://gtsst.uapa.edu.do/crecenta/...`, **quita el prefijo** y
pasa la petición a gunicorn; Django vuelve a poner el prefijo en todo lo que genera.

## Qué hace Django (ya configurado en `config/settings/prod.py`)

- `FORCE_SCRIPT_NAME = "/crecenta"`: `reverse`, `{% url %}`, redirecciones, login de allauth,
  manifest y service worker de la PWA llevan el prefijo.
- `STATIC_URL = "/crecenta/static/"`: WhiteNoise sirve los estáticos desde el mismo gunicorn (el
  proxy no necesita una regla aparte).
- Cookies `crecenta_sessionid` y `crecenta_csrftoken` con ruta `/crecenta/`: no chocan con las
  de otras apps Django del mismo dominio.
- `CSRF_TRUSTED_ORIGINS = ["https://gtsst.uapa.edu.do"]`.
- Los comprobantes subidos (`MEDIA_ROOT`) **no** se publican: solo salen por la vista autenticada.
  No agregues una regla del proxy para `/crecenta/media/`.

Cada valor se puede cambiar con su variable de entorno o en la tabla `parameters`
(`FORCE_SCRIPT_NAME`, `STATIC_URL`, `MEDIA_URL`, `DJANGO_CSRF_TRUSTED_ORIGINS`).

## Parámetros obligatorios (tabla `parameters` o variables de entorno)

| Clave | Valor |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` (variable de entorno del servicio) |
| `DJANGO_ALLOWED_HOSTS` | `gtsst.uapa.edu.do` |
| `DJANGO_SECRET_KEY` | una clave larga y secreta |

## gunicorn

```sh
gunicorn config.wsgi:application --bind 127.0.0.1:8013 --workers 3 --timeout 60
```

(Puerto de producción: 8013.)

## nginx

Dentro del `server { ... }` de `gtsst.uapa.edu.do` (el que ya tiene el certificado HTTPS):

```nginx
location = /crecenta { return 301 /crecenta/; }

location /crecenta/ {
    # La barra final de proxy_pass quita «/crecenta» antes de pasar la petición a Django.
    proxy_pass http://127.0.0.1:8013/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_redirect off;
    client_max_body_size 12m;  # fotos de comprobantes
}
```

## Apache (si el servidor usa Apache en vez de nginx)

```apache
RedirectMatch 301 ^/crecenta$ /crecenta/
ProxyPreserveHost On
RequestHeader set X-Forwarded-Proto "https"
ProxyPass        /crecenta/ http://127.0.0.1:8013/
ProxyPassReverse /crecenta/ http://127.0.0.1:8013/
```

## Pasos en cada actualización

```sh
python manage.py migrate
python manage.py collectstatic --noinput
# reiniciar gunicorn, el worker de Celery y Celery beat
```

## Después del primer despliegue

- **Inicio de sesión con Google**: en Google Cloud Console agrega la URI de redirección
  `https://gtsst.uapa.edu.do/crecenta/cuenta/google/login/callback/`.
- **Comprobación de salud del proxy**: `https://gtsst.uapa.edu.do/crecenta/salud/` (no se redirige
  a HTTPS).
- **PWA**: instalada desde `https://gtsst.uapa.edu.do/crecenta/`; su alcance es solo
  `/crecenta/`, así que no interfiere con las otras aplicaciones del dominio.
- **HSTS**: `prod.py` envía `Strict-Transport-Security` con `includeSubDomains` y `preload` para
  todo `gtsst.uapa.edu.do`. Si alguna otra app del dominio o de sus subdominios todavía usa HTTP,
  pon `SECURE_HSTS_SECONDS=0` en los parámetros hasta que todas usen HTTPS.
