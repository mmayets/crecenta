# Registro de decisiones

Decisiones tomadas donde el encargo no especifica. Formato: decisión · motivo.

## Generales

1. **Python 3.12 en Docker**; el código también corre en 3.13 (el entorno de desarrollo actual). · El encargo fija 3.12.
2. **Usuario personalizado con email como identificador** (`accounts.User`, sin `username`), creado desde la primera migración. · Cambiar el modelo de usuario después es costoso.
3. **Rutas con el espacio en la URL** (`/e/<workspace_uuid>/…`) y el último espacio usado en la sesión. · Hace explícito el aislamiento y permite abrir dos espacios en pestañas distintas.
4. **Aislamiento**: `WorkspaceScopedQuerySet.for_workspace(ws)` + `WorkspaceRequiredMixin`; un espacio ajeno responde **404** (no 403) para no revelar su existencia.
5. **Moneda única por espacio** (DOP por defecto, USD opcional). Las cuentas heredan la moneda del espacio; no hay conversión en Fase 1. · Evita tipos de cambio inventados.
6. **Montos siempre positivos** con `direction` (`in|out`). · Elimina errores de signo.

## Motor personal

7. **Período = ciclo mensual anclado al primer día de cobro** del ingreso principal (p. ej. 25 → 24 del mes siguiente); dentro del ciclo cada cobro es un `pay_event`. Para quincenal el plan muestra el mes y su reparto por quincena. · Coincide con cómo la gente piensa su presupuesto y permite la verificación por fechas.
8. **Asignación a cobros**: cada salida programada se asigna al último cobro anterior o igual a su vencimiento; el ahorro y los esenciales se reparten en proporción al monto de cada cobro. · Regla simple que reproduce "3,500 por quincena".
9. **Reserva para variaciones**: mínimo `reserve_pct` (10 % por defecto, configurable 5–10 %) de esenciales variables. Si el usuario indica un monto de ocio deseado, el restante tras el ocio va a la reserva (siempre ≥ el mínimo); si no lo indica, se reserva el mínimo y el resto va a discrecional. · Así el caso RD$50,000 da ocio 5,000 + reserva 3,000 exactos.
10. **Estado del plan**: `viable` si el total cuadra y no hay faltantes en la línea de tiempo con reserva ≥ mínimo; `ajustado` si cuadra pero la reserva queda por debajo del mínimo o el saldo cae a menos del 5 % del ingreso en algún día; `no_viable` si falta dinero en el total o en alguna fecha.
11. **Fecha de vencimiento inexistente** (día 31 en un mes de 30): se usa el último día del mes.
12. **"Disponible para gastar" puede ser negativo** y se muestra como faltante con advertencia; nunca se trunca a cero para no ocultar el problema.
13. **Promedio de historial** para esenciales: se usa solo si hay ≥ 2 períodos completos registrados; si no, el estimado del usuario.

## IA

14. **Proveedor `fake`** determinístico para tests y para correr sin claves; se selecciona con `AI_PROVIDER`.
15. **Verificación de cifras**: se extraen de la narrativa todos los números monetarios (con `RD$`/`US$` o ≥ 100 con separadores de miles) y `impacto_rd`; cada uno debe pertenecer al conjunto permitido (valores de `computed`, alternativas calculadas, y sus diferencias). Si alguno no coincide, se reintenta una vez indicando el error y luego se usa la narrativa de reglas. Los porcentajes deben coincidir con porcentajes calculados.
16. **Sin consentimiento de IA** la app funciona completa con narrativas por reglas y registro manual; OCR, voz y modo conversacional quedan deshabilitados con explicación.
17. **Rate limiting** propio sobre la caché de Django (Redis): 30 llamadas de IA/hora y 200/día por usuario, configurable. · Evita otra dependencia.
18. **No se guardan prompts ni respuestas** en `AIInteraction` salvo `AI_DEBUG_LOG=True`.

## Frontend / PWA

19. **Íconos**: sprite SVG inline con un subconjunto de Lucide (licencia ISC) y la etiqueta `{% icon %}`.
20. **htmx, Alpine.js y ApexCharts** se guardan en `static/vendor/` con versión fijada. Tailwind se compila con el CLI standalone en el build de Docker; el CSS compilado también se versiona para que el proyecto funcione sin el CLI en desarrollo.
21. **Service worker servido desde `/sw.js`** por una vista de Django (scope raíz).
22. **Background Sync** cuando el navegador lo soporta (Chromium/Android); en iOS se sincroniza en `online`/al abrir la app. El endpoint es idempotente por `client_uuid`.
23. **Comprobantes**: máximo 10 MB, tipos `image/jpeg|png|webp|heic` y `application/pdf`; servidos solo por vista autenticada con `Content-Disposition`.

## Alcance

24. **Fase 1 incluye modelos mínimos de negocio** (`BusinessProfile`, `Product`) y las funciones puras de `pricing` (margen/markup) con tests, solo para que la opción "Negocio/Ambos" cree el espacio y `seed_demo` cargue el producto de costo RD$600. La UI de negocio llega en Fase 2.
