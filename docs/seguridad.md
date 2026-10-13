# Revisión de seguridad y privacidad — Fase 1

Revisión hecha al cierre de la Fase 1 (paso 12). Cada punto indica cómo se cumple y qué lo verifica.

## Resultado

| Herramienta | Resultado |
|---|---|
| `manage.py check --deploy` (settings de producción) | Sin observaciones |
| `pip-audit` sobre las dependencias de producción | Sin vulnerabilidades conocidas |
| `ruff` con reglas de seguridad (`S`, equivalente a bandit) | Sin hallazgos |
| Test automático de aislamiento (`tests/test_aislamiento.py`) | Todas las rutas de dominio responden 404 a un espacio ajeno (GET y POST) |
| Navegador (Chromium) | Sin violaciones de la Content-Security-Policy |

## Controles

**Aislamiento entre personas**
- Todas las rutas de datos viven bajo `/e/<espacio>/` y pasan por `workspace_required`, que exige sesión y membresía; un espacio ajeno responde 404 (no revela que existe). El test de aislamiento recorre automáticamente todas esas rutas.
- Las consultas usan `for_workspace()`, que falla si no recibe un espacio. Cuentas, categorías, planes, alertas y comprobantes que llegan por id (formularios, sincronización offline, edición) se buscan solo dentro del espacio de la URL; hay tests con ids de otro usuario.
- Exportar entrega solo los espacios propios (test con datos de otra persona); eliminar la cuenta no toca datos ajenos (test).

**Autenticación y sesión**
- django-allauth con correo y contraseña; validadores de contraseña de Django; límite de intentos fallidos de inicio de sesión.
- Eliminar la cuenta exige escribir el correo **y la contraseña** (las cuentas creadas con Google solo el correo).
- Al cerrar sesión se borran las páginas guardadas por el service worker.

**Web**
- CSRF en todos los formularios y en el endpoint de sincronización (el service worker reenvía el token del formulario).
- Content-Security-Policy estricta (`script-src 'self'`, sin JavaScript en línea, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`, `Permissions-Policy` (cámara y micrófono solo en el sitio).
- Producción: HTTPS obligatorio, HSTS con preload, cookies `Secure`, secretos solo por variables de entorno, ruta del admin configurable (`DJANGO_ADMIN_URL`).
- Plantillas con autoescape; el único `|safe` es la lista de archivos del service worker, generada por el servidor.

**Archivos (comprobantes)**
- Tipo real verificado por la firma del archivo (JPG, PNG, WEBP, HEIC, PDF), máximo 10 MB, nombre aleatorio sin el nombre original.
- Nunca se sirven como estáticos: solo por una vista autenticada con `Cache-Control: private, no-store`, `nosniff` y `Content-Security-Policy: sandbox`. Bucket S3 privado en producción.
- Límite de 60 subidas por hora por persona.

**IA y datos personales**
- Nada se envía a la IA sin consentimiento explícito (revocable en Configuración).
- Se envía lo mínimo: el plan calculado sin identificadores internos, sin nombres ni números de cuenta, sin correo; el prompt del OCR ordena no transcribir tarjetas, cuentas ni documentos (y el esquema no tiene campos para eso).
- La IA no ejecuta acciones: devuelve JSON validado con un esquema; las cifras se verifican contra el motor y todo queda como propuesta.
- Límite de 30 llamadas por hora y 200 por día por persona; registro de uso sin guardar prompts ni respuestas (salvo `AI_DEBUG_LOG`).

**Abuso**
- Sincronización offline: lotes de máximo 100 elementos y 120 envíos por minuto por persona (429 al superarlo; el service worker reintenta luego).

## Fase 2 (negocio)

- **Aislamiento**: además del recorrido general de rutas, `tests/test_aislamiento_negocio.py` prueba las rutas de negocio contra el negocio de otra persona, objetos ajenos referidos por id en la URL del propio negocio (404) y ids ajenos en formularios (producto, cuenta, categoría, cuenta personal: rechazados). Los servicios validan por su lado que cuenta, cliente, producto y deuda pertenezcan al espacio.
- **Transferencias entre espacios** solo entre espacios de los que la persona es dueña y propietaria (membresía), de la misma moneda; la cuenta personal se toma siempre del espacio personal de quien hace la solicitud.
- **Idempotencia y concurrencia**: ventas, deudas, cobros, pagos y transferencias con `client_uuid` y restricción única; cobros y pagos bloquean la deuda (`select_for_update`) y nunca superan el saldo (también una restricción en la base de datos).
- **Parámetros libres de htmx** (avisos de gasto y de retiro): montos no válidos, infinitos, negativos o que no caben en 14 dígitos se ignoran (antes un valor como `1e999999` producía un error 500 en el aviso de gasto de la Fase 1; corregido).
- **IA del negocio**: misma tubería que la personal (consentimiento, límites, esquema, verificador de cifras, narrativa por reglas); la extracción conversacional no se guarda hasta confirmar y el prompt prohíbe transcribir cuentas, tarjetas, RNC o cédulas.
- **Privacidad**: la exportación incluye los datos de negocio (productos y componentes, gastos, clientes, proveedores, ventas y líneas, por cobrar y por pagar, perfil, metas y transferencias entre espacios) y eliminar la cuenta borra todo, incluido un negocio con ventas y deudas (probado con la demo completa).
- **Dependencias**: `pip-audit` sin vulnerabilidades conocidas al cierre de la fase.

## Pendiente para fases siguientes

- Verificación del correo es `optional` en desarrollo y `mandatory` en producción; evaluar 2FA (allauth MFA) cuando haya negocios con varias personas.
- Cifrado de comprobantes en reposo depende del almacenamiento (activar cifrado del bucket S3).
- Política de retención/borrado de `AIInteraction` y de alertas antiguas.
