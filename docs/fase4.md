# Fase 4 — Equipo, producción con insumos, monedas y ventas sin conexión: propuesta de diseño

> Para revisión **antes de escribir código**. Recoge lo que quedó fuera de la Fase 3 y lo que más
> pide un negocio pequeño cuando crece. Se mantiene el principio rector: **los números los calcula
> el código; la IA explica.**

## 1. Alcance propuesto

| Tema | Qué resuelve | Incluido |
|---|---|---|
| **Equipo y roles** | Un empleado registra ventas sin ver ganancias, retiros ni datos personales del dueño | Sí |
| **Producción con insumos (recetas)** | El bizcocho descuenta harina, huevos y caja del inventario; costo real de lo elaborado | Sí |
| **Negocio en otra moneda** | Negocio en US$ y persona en RD$: retiros y aportes con tasa de cambio | Sí |
| **Ventas sin conexión** | Registrar una venta sin internet y que se sincronice sin duplicarse (como los gastos) | Sí |
| **NCF en ventas y compras + exportación de apoyo 606/607** | Guardar el comprobante fiscal y sacar un archivo para el contador | Opcional (ver decisión 7) |
| Declaraciones ante la DGII | Llenar y presentar formularios | No (fuera de alcance) |

---

## 2. Equipo y roles

Solo los **espacios de negocio** se comparten; el espacio personal nunca.

| Permiso | Propietario | Administrador | Vendedor |
|---|:-:|:-:|:-:|
| Registrar ventas, cobros, compras y gastos | ✓ | ✓ | Ventas y cobros |
| Ver inventario y productos (sin costos para el vendedor) | ✓ | ✓ | ✓ (precio y existencia) |
| Ver costos, márgenes, reportes, ITBIS y el inicio con ganancias | ✓ | ✓ | — |
| Plan de negocio, metas, alertas | ✓ | ✓ | — |
| Retiros y aportes del propietario | ✓ | — | — |
| Invitar, cambiar roles y quitar personas | ✓ | — | — |
| Exportar, borrar el espacio | ✓ | — | — |

- **Invitación por enlace**: el propietario escribe un correo y un rol; se genera un enlace de un
  solo uso que vence en 7 días. Solo puede aceptarlo quien inicie sesión **con ese correo**.
- Los permisos se comprueban en el servidor (decorador `workspace_required(perm=…)`), no solo
  ocultando botones; el test de aislamiento suma un recorrido por rol.
- Cada registro ya guarda `created_by`: se muestra "registrado por" en ventas y movimientos.
- Quitar a una persona no borra lo que registró.

## 3. Producción con insumos (recetas)

1. **Insumo** = producto con inventario que no se vende (harina en libras, cajas en unidades); se
   compra con la pantalla de compras y usa el **mismo costo promedio** de la Fase 3.
2. **Receta**: cada producto elaborado puede tener ingredientes `(insumo, cantidad por unidad)`.
3. **Al vender** un producto con receta se descuentan sus insumos y el costo de lo vendido es
   la suma de `cantidad × costo promedio` de cada insumo, más los componentes de costo que no son
   insumos (comisión, entrega). No hay inventario de producto terminado (se hace y se vende).
4. Sin existencias de un insumo: se permite y avisa, igual que en la Fase 3.
5. El precio sugerido y el plan usan el **costo de receta actual**.

## 4. Negocio en otra moneda

- El negocio puede tener moneda distinta de la persona (p. ej. US$ y RD$).
- En retiros y aportes se escribe la **tasa del día** (no se consulta ningún servicio externo):
  la pata del negocio va en su moneda y la de la persona en la suya; se guarda la tasa usada.
- Todo cálculo dentro de un espacio sigue en una sola moneda; no se suman monedas.

## 5. Ventas sin conexión

- La venta rápida funciona sin internet como el registro de gastos: se guarda en el teléfono con
  su `client_uuid` y se envía al reconectar (el servidor ya es idempotente para ventas).
- Sin conexión no hay aviso de existencias (se calcula al sincronizar y queda como alerta).

## 6. Plan de la Fase 4 (pasos verificables)

| # | Paso | Verificación clave |
|---|---|---|
| D1 | Roles y permisos (modelo, decorador, matriz) | Test por permiso y rol; recorrido de rutas por rol |
| D2 | Invitaciones (crear, aceptar, vencer, quitar) | Solo el correo invitado acepta; enlace de un uso |
| D3 | Vistas según rol (inicio y menús del vendedor sin costos) | El HTML del vendedor no contiene costos ni ganancias |
| D4 | Insumos y recetas (puro + ORM) | Costo de receta exacto; venta descuenta insumos |
| D5 | Recetas en precios, plan e indicadores | Precio sugerido y plan usan el costo de receta |
| D6 | Moneda distinta y tasa en transferencias | Cada pata en su moneda; tasa guardada; validaciones |
| D7 | Ventas sin conexión (service worker + sincronización) | E2E: venta offline → reconexión → una sola venta |
| D8 | (Opcional) NCF y exportación 606/607 de apoyo | Formato validado por tests |
| D9 | Cierre: demo con un vendedor y recetas, seguridad, docs | `seed_demo` y aislamiento por rol |

## 7. Decisiones que necesito confirmar

1. **Tres roles** (propietario, administrador, vendedor) con la matriz de arriba; el espacio
   personal nunca se comparte.
2. **Invitación por enlace** de un solo uso, 7 días, válida solo para el correo invitado (sin
   enviar correos desde la app: el propietario comparte el enlace por WhatsApp o como prefiera).
3. **Recetas sin inventario de producto terminado**: los insumos se descuentan al vender.
4. **Tasa de cambio manual** en cada transferencia entre monedas distintas.
5. **Ventas sin conexión** con la misma cola del teléfono que los gastos.
6. **El vendedor no ve costos ni ganancias**, pero sí precios y existencias.
7. **NCF + exportación 606/607**: ¿la incluyo? Es útil para el contador en RD, pero el formato
   oficial cambia y la app no puede garantizar su validez; propongo hacerlo como "archivo de apoyo"
   que el contador revisa. Si no lo necesitas, lo dejo fuera.
