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
10. **Estado del plan**: `no_viable` si falta dinero en el total o en alguna fecha; `ajustado` si cuadra pero la reserva queda bajo el mínimo, el ocio deseado no alcanza o el saldo estimado baja de la reserva mínima en algún día; `viable` en otro caso. *(Actualizada en el paso 4: el umbral de "saldo bajo" es la reserva mínima, no el 5 % del ingreso.)*
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

## Paso 1 — esqueleto

25. **Django 5.2 (LTS)** y `uv` para dependencias (`pyproject.toml` + `uv.lock`). · Versión con soporte extendido; `uv` hace instalaciones reproducibles y rápidas en Docker.
26. **`IncomeSource.net_amount` es el monto de cada cobro**, no el mensual (quincenal de RD$25,000 → RD$50,000 al mes). · La línea de tiempo de caja necesita el monto real de cada fecha. La interfaz ofrece escribir el total mensual y lo divide.
27. **Ingreso variable sin fecha** se considera recibido al inicio del período y se marca como estimado; con fechas, se usa cada fecha. Para elegir el ingreso principal (día ancla) se ignoran los ingresos semanales; si solo hay semanales, el período es el mes calendario.
28. **`LANGUAGE_CODE = "es"`** (Django no trae traducción `es-DO`); el formato de montos (`RD$50,000.00`) lo da `core.money.fmt`, no la localización de Django, para que sea idéntico en todo el sistema. El HTML declara `lang="es-DO"`.
29. **`ATOMIC_REQUESTS = True`**. · Cada petición que registra dinero es todo-o-nada.
30. **CSP estricta sin CDN** (`script-src 'self'`): se usará la build CSP de Alpine.js para no requerir `unsafe-eval`.
31. **Tests contra PostgreSQL real** (no SQLite) para que restricciones, `UniqueConstraint` condicionales y tipos coincidan con producción. Caché local en memoria y Celery en modo *eager* en tests.
32. **`split_proportionally`** usa el método del mayor residuo: las partes siempre suman exactamente el total, sin centavos perdidos.

## Paso 2 — espacios y aislamiento

33. **Todas las rutas de dominio se montan en `config/workspace_urls.py`** bajo `/e/<uuid:ws>/`; cada app agrega su `ws_urls.py` con un namespace propio (`espacio`, `ledger`, …). El test `tests/test_aislamiento.py` recorre ese módulo y comprueba, para cada ruta y para GET y POST, que un espacio ajeno o inexistente responde 404 y que un anónimo va al login. · Una vista nueva queda protegida y probada sin escribir un test extra.
34. **`WorkspaceScopedQuerySet.for_workspace(ws)`** falla si no recibe un espacio guardado, para que un olvido no devuelva datos de todos los espacios.
35. **Rol único `owner`** en `Membership` durante la Fase 1; la tabla ya permite compartir un espacio (p. ej. con un socio o contador) más adelante sin migrar datos.
36. **`WorkspaceTransfer` se implementa en la Fase 2** junto con los movimientos del propietario (el encargo ubica las transferencias entre espacios en esa fase y dependen de `ledger`).
37. **Orden de espacios**: primero el personal, luego los negocios por antigüedad. La app recuerda el último espacio abierto en la sesión.
38. **El Paso 0 del onboarding ("¿Para qué usarás la app?") vive en `workspaces`** porque su único efecto es crear los espacios; es idempotente (repetirlo no duplica espacios). El resto del wizard llega en el paso 9.

## Paso 3 — ledger

39. **Clasificación de movimientos** (`ledger/services/classification.py`): ingreso/venta son ingreso; gasto, pago de deuda y compra de inventario son gasto; transferencia interna, retiro de efectivo y préstamo (recibido u otorgado) son neutros. El pago de deuda cuenta como gasto en el **presupuesto personal** porque consume la cuota comprometida; en el negocio (Fase 2) el abono a capital no será gasto del resultado.
40. **Transferencias = dos movimientos enlazados** (`transfer_pair`), salida en la cuenta origen y entrada en la destino. El total de las cuentas no cambia. Una transferencia puede llevar la categoría "Ahorro" para medir aportes a la meta sin contarlos como gasto.
41. **Tarjeta de crédito como cuenta con saldo negativo** (lo que se debe). Gastar con tarjeta es gasto; pagar la tarjeta desde el banco es transferencia interna (no se cuenta dos veces).
42. **Solo los movimientos confirmados mueven saldos y presupuesto.** Los borradores `pendiente_revision` (comprobantes leídos por IA, texto/voz) esperan la confirmación del usuario.
43. **No se guardan números de cuenta ni de tarjeta**: la cuenta solo tiene nombre y tipo.
44. **Catálogo de categorías del sistema en código** (`ledger/system_categories.py`) y creación automática al crear el espacio (señal `post_save`), junto con una cuenta "Efectivo" para que el registro rápido siempre tenga cuenta. Las categorías del sistema se pueden renombrar y reclasificar pero no eliminar (se archivan).
45. **Sincronización offline**: endpoint `POST /e/<ws>/movimientos/sync/` con `{"items": [...]}` (máx. 100). Cada elemento responde `creado`, `existente` o `error` con mensajes por campo, para que el dispositivo vacíe su cola. Gana la primera escritura: un reenvío con el mismo `client_uuid` y datos distintos devuelve el original sin modificarlo. La pata de entrada de una transferencia usa un UUID derivado (uuid5) del `client_uuid`. Cuentas y categorías se buscan solo dentro del espacio de la URL: un id de otro usuario se trata como inexistente. El endpoint exige token CSRF.

## Paso 4 — motor del plan personal

46. **Línea de tiempo de caja día a día**: cada cobro se acredita antes de los pagos del mismo día; compromisos y cuotas salen en su vencimiento; el ahorro sale en el cobro al que se asigna; esenciales y ocio se consumen de forma lineal en el período (acumulado redondeado para que la suma cuadre al centavo); la reserva no es una salida. El faltante se marca en cada vencimiento con saldo negativo (con el compromiso que vence) y en el primer día de cada tramo negativo por gasto variable ("Gastos del día a día").
47. **La viabilidad cuenta solo lo cobrado en el período** (`opening_cash = 0` al generar el plan): el plan no depende de ahorros previos. Se informa como supuesto.
48. **Reparto por cobro**: los vencimientos van al cobro que los cubre (decisión 8); el ahorro se reparte según el monto de cada cobro; esenciales, ocio y reserva según lo que le queda a cada cobro después de sus vencimientos y su ahorro. Así ningún cobro queda con sobrante negativo cuando el plan es viable.
49. **"Disponible para gastar"** descuenta lo que el plan asignó a los **cobros ya recibidos**: compromisos no pagados que esos cobros cubren (los pagos se reconocen por categoría y se aplican a los vencimientos en orden de fecha; sin categoría, un vencimiento pasado se da por pagado), ahorro aún no apartado y la reserva de esos cobros. Lo que se pagará con el próximo cobro no compromete el dinero de hoy. Puede ser negativo.
50. **Cuentas de ahorro** (`Account.is_savings`): su saldo cuenta en "Disponible en tus cuentas" pero no en "Disponible para gastar". Apartar el ahorro = transferir a una cuenta de ahorro con la categoría "Ahorro".
51. **Montos por ocurrencia**: el monto de un compromiso es el de cada vencimiento (como el ingreso, decisión 26). Compromisos quincenales vencen en `due_day` y `due_day ± 15`. Compromisos anuales quedan para la Fase 3.
52. **Ahorro**: diario usa los días reales del período; diario con días seleccionados cuenta esos días de la semana; semanal cuenta las semanas que inician en el período (4 o 5); quincenal = 2; mensual = 1. Nunca se planifica más de lo que falta para la meta. Lo aportado antes del período (transferencias con la categoría de la meta) se suma a lo ahorrado.
53. **Alternativas por reglas** (`alternatives.py`): reducir ocio, separar el ahorro en el último cobro, usar la reserva para el ocio, recortar hasta 15 % de los esenciales marcados como reducibles, bajar el ahorro lo justo, aplazar el ahorro y, si ninguna sola basta, una combinada. Solo se muestran las que mejoran el estado o reducen el faltante, cada una recalculada por el motor; se ordenan por estado resultante y dejan al final las que tocan algo marcado como prioritario.
54. **Esenciales desde el historial**: con al menos dos períodos completos registrados, el promedio de gasto de esos períodos reemplaza al estimado del usuario por categoría (se informa como supuesto).
55. **`BudgetPeriod` y `BudgetLine` se crean en el paso 6**, al aceptar un plan; hasta entonces el plan se calcula a partir de los datos actuales.

## Paso 5 — capa de IA

56. **Qué cuenta como cifra en la narrativa** (actualiza la decisión 15): montos con `RD$`/`US$`/`$`, seguidos de "pesos"/"dólares", con separador de miles o con 2 decimales. Números sueltos sin formato (días, años, cantidades) no se tratan como dinero. Se aceptan los montos del plan calculado (incluidos alternativas y supuestos) y la diferencia entre dos de ellos; los porcentajes deben aparecer en el plan. También se validan `impacto_rd`, el `estado` y los `cambios` de cada alternativa, que además debe citar el `codigo` de una alternativa del motor.
57. **Flujo de una llamada** (`ai/services/client.py`): consentimiento → límite de uso → plantilla → proveedor → JSON + esquema Pydantic + validador de negocio → si falla, un reintento que incluye los errores → si vuelve a fallar, respuesta por reglas (o error explícito cuando no existe respaldo, p. ej. OCR). Una falla del proveedor cuenta como intento fallido.
58. **Un registro `AIInteraction` por llamada** (no por intento) con proveedor, modelo, versión del prompt, tokens sumados, latencia, intentos, resultado y errores de validación. El contenido (prompts y respuestas) solo se guarda con `AI_DEBUG_LOG=True`.
59. **Salida estructurada nativa**: Gemini con `response_json_schema` y OpenAI con `response_format: json_schema` (no estricto, porque el modo estricto exige que todo campo sea obligatorio). Igual se valida siempre en el servidor. El esquema también se agrega al final del prompt para que funcione con cualquier modelo.
60. **Proveedor `fake` en desarrollo**: para el plan responde con la narrativa por reglas; para OCR, voz, texto libre y onboarding conversacional no tiene respuesta y esas funciones muestran "IA no disponible". Así la app es usable sin claves y nunca simula una extracción.
61. **Plantillas versionadas** `ai/prompts/<nombre>.<versión>.md` con secciones `## system` y `## user` y marcadores `{{ nombre }}`; la versión vigente se fija en `ai/services/prompts.py::VERSIONS` y se registra en cada `AIInteraction`.
62. **El plan que recibe la IA no lleva identificadores internos** (`serialize_plan(..., include_refs=False)`); los montos van como texto con 2 decimales.
63. **SDK oficiales** `google-genai` y `openai`, importados solo al usar ese proveedor. Modelos configurables por variables de entorno (`GEMINI_MODEL`, `OPENAI_MODEL`, `OPENAI_TRANSCRIBE_MODEL`).

## Paso 6 — plan con IA y versiones

64. **Cálculo síncrono, explicación asíncrona**: al pedir un plan, el motor calcula y guarda la versión al instante (estado `generando`, las cifras ya se ven); la narrativa corre en Celery (`planning.narrate_plan`) y deja la versión en `propuesta`. La tarea se encola al confirmar la transacción (`on_commit`) y nunca deja una versión en `generando`: ante cualquier falla usa la narrativa por reglas. Se agregó el estado `generando` a los del encargo.
65. **`inputs_snapshot` reproduce el cálculo**: guarda las entradas del motor (sin cuentas, saldos por cuenta ni datos de la persona). Recalcular desde el snapshot da exactamente el mismo `computed` (hay test). La IA recibe el plan sin identificadores internos y las preferencias con el nombre de la categoría.
66. **Editar = nueva versión**: la persona puede aplicar una alternativa del motor, cambiar ocio deseado, porcentaje de reserva (0–50 %), montos de esenciales y aportes de ahorro. Se crea una nueva propuesta recalculada por el motor (con `parent` y `edits`) y la anterior pasa a `reemplazado`. Cambios inválidos no tocan la propuesta.
67. **Aceptar**: crea `BudgetPeriod` (con el reparto por cobro) y una `BudgetLine` por línea del plan; la versión aceptada anterior del mismo período y las demás propuestas abiertas pasan a `reemplazado`, y su presupuesto deja de estar vigente (una restricción única garantiza un solo presupuesto vigente por período).
68. **Plan aceptado vigente**: `accepted_result()` recalcula el resultado desde el snapshot de la versión aceptada; lo usarán el inicio, las alertas y "Disponible para gastar" en lugar de los datos actuales cuando exista.
69. **Sin cobros no hay plan viable**: si en el período no hay ningún cobro, el estado es `no_viable` aunque no haya gastos.
70. **Datos faltantes** con prioridad (alta, media, baja), mensaje, impacto en el plan y pregunta sugerida; se muestran en el plan y se envían a la IA.

## Paso 7 — alertas

71. **Las alertas se evalúan contra el plan aceptado vigente**; si no hay, contra el plan calculado con los datos actuales (se indica en "datos usados"). Sin ingresos no se evalúa.
72. **Cuándo se evalúa**: cada día a las 7:00 (celery beat, `alerts.evaluate_all`) y tras cada movimiento confirmado (señal `post_save`, al confirmar la transacción). Las ráfagas de movimientos (sincronización offline) se agrupan en una sola evaluación con una espera de 5 segundos.
73. **Sin duplicados**: cada situación tiene una clave (`dedupe_key`, incluye el período). Reevaluar actualiza la alerta abierta; una alerta descartada no vuelve en el período; una alerta abierta cuya condición desaparece pasa sola a `resuelta` (y se reabre si la situación vuelve). "Buen desempeño" no se resuelve sola.
74. **Reglas** (umbral y días configurables por espacio, cada una se puede desactivar): consumo ≥ 80 % (≥ 100 % es urgente) por esencial y para el ocio en conjunto (los gastos sin categoría cuentan como ocio); riesgo de fin de período por proyección lineal **solo de gastos variables** desde el día 3, con el límite diario sugerido; pago en los próximos 3 días que el dinero de las cuentas de uso diario no cubre (si un cobro llega antes del vencimiento no se alerta); ahorro de cobros recibidos hace 3 días o más que no se apartó, con propuesta de reparto entre los próximos cobros; "Disponible para gastar" negativo; buen desempeño pasada la mitad del período con gasto variable ≤ 90 % de lo previsto a la fecha y ahorro al día.
75. **Aviso previo al registrar un gasto** (`purchase_warnings`): si el gasto usa dinero comprometido o supera el presupuesto de su categoría. No se guarda como alerta: la persona decide si registra el gasto.
76. **Acciones sugeridas** (`revisar_plan`, `limite_diario`, `mover_dinero`, `repartir_ahorro`) se guardan como datos; aplicarlas siempre requiere que la persona lo apruebe desde la interfaz.
77. **Notificaciones**: en la Fase 1 las alertas se muestran dentro de la app (con contador de nuevas). Las notificaciones push se evaluarán junto con la PWA.
