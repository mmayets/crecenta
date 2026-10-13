# Fase 3 — Inventario, reportes y pendientes: propuesta de diseño

> Para revisión **antes de escribir código**. El encargo dejó para esta fase el inventario
> (`InventoryMovement`: "en la fase 2 usar el costo unitario por venta"). Propongo sumar los
> pendientes anotados en las fases 1 y 2 que más valor dan con menos riesgo, y dejar para una
> Fase 4 lo que cambia la seguridad o el modelo de datos de fondo (varias personas por negocio y
> varias monedas). Se mantiene el principio rector: **los números los calcula el código; la IA
> explica.**

## 1. Alcance propuesto

| Tema | Qué resuelve | Incluido |
|---|---|---|
| **Inventario** | Cuántas unidades tengo, cuánto vale lo que tengo, costo real de lo vendido, mermas | Sí (núcleo) |
| **Compras de mercancía** | Registrar compras por producto (contado o a crédito) que alimentan el inventario | Sí |
| **Editar una venta** | Hoy se anula y se vuelve a registrar | Sí |
| **Compromisos anuales (persona)** | Marbete, seguro, inscripción del colegio: hoy no se pueden registrar | Sí |
| **Resumen de ITBIS** | ITBIS cobrado − ITBIS pagado en compras = estimado por pagar (informativo) | Sí |
| **Reportes por mes** | Estado de resultados y flujo de efectivo de los últimos meses, gráfico y exportación CSV | Sí |
| Varias personas por negocio (roles) | Un empleado que registra ventas | No → Fase 4 |
| Monedas distintas persona/negocio | Tipo de cambio | No → Fase 4 |
| Insumos con recetas (producción) | Descontar harina al hacer un bizcocho | No → Fase 4 |

---

## 2. Reglas del inventario (lo más importante a confirmar)

1. **Qué se controla**: solo los productos marcados "controlo su inventario" — mercancía que se
   compra y se revende (colmado, tienda) o productos terminados que se compran hechos. Lo que se
   produce con insumos (bizcocho) sigue con su costo por componentes hasta la Fase 4.
2. **Método de costo: promedio ponderado.** Cada compra recalcula el costo promedio:
   `nuevo promedio = (unidades × promedio + unidades compradas × costo de compra) / total`.
   Es el más simple de explicar y el habitual en pequeños negocios.
3. **Al vender** un producto con inventario, el costo guardado en la línea (`unit_cost_snapshot`)
   es el **costo promedio del momento** y se registra una salida. Así los indicadores de la Fase 2
   no cambian de fórmula: el costo de lo vendido pasa a ser real en vez de estimado.
4. **Vender sin existencias se permite** (la persona no siempre registra todo), con aviso al
   vender y una alerta de "existencia negativa"; el costo usado es el último promedio conocido.
5. **Comprar mercancía no es gasto**: es efectivo que se convierte en inventario (como ya lo trata
   `compra_inventario`). Pasa a gasto cuando se vende (costo de lo vendido) o se pierde.
6. **Mermas y ajustes**: una merma (vencido, roto, robado) o un ajuste negativo por conteo es
   **gasto del mes** (categoría nueva "Mermas y ajustes") al costo promedio; un ajuste positivo
   reduce ese gasto. No mueven efectivo.
7. **Inventario inicial**: al activar el control se registra la existencia y el costo de partida
   (no es compra ni mueve efectivo).
8. **Anular o editar** una venta o una compra revierte sus movimientos de inventario; el promedio
   se recalcula desde el historial del producto (es determinístico).

| Movimiento | Unidades | Costo promedio | ¿Resultado del mes? | ¿Efectivo? |
|---|---|---|---|---|
| Inventario inicial | + | fija el de partida | No | No |
| Compra de contado | + | se recalcula | No | Sí, salida |
| Compra a crédito | + | se recalcula | No | No (hasta pagar la CxP) |
| Venta | − | no cambia | Sí, costo de lo vendido | Contado sí / crédito al cobrar |
| Merma / ajuste − | − | no cambia | Sí, gasto "Mermas y ajustes" | No |
| Ajuste + | + | no cambia | Reduce ese gasto | No |

---

## 3. Modelos nuevos y cambios

```mermaid
erDiagram
    Product ||--o{ InventoryMovement : ""
    Purchase ||--o{ PurchaseLine : ""
    Product ||--o{ PurchaseLine : ""
    PurchaseLine ||--o| InventoryMovement : "entrada"
    SaleLine ||--o| InventoryMovement : "salida"
    Purchase |o--o| Payable : "si es a crédito"
    Purchase ||--o{ Transaction : "si es de contado"

    Product {
        bool tracks_inventory
        decimal stock_minimum
        decimal stock "derivado, cacheado"
        decimal average_cost "derivado, cacheado"
    }
    InventoryMovement {
        enum kind "inicial|compra|venta|merma|ajuste"
        date date
        decimal qty "con signo"
        decimal unit_cost
        decimal value "qty × costo"
        fk purchase_line
        fk sale_line
        uuid client_uuid
    }
    Purchase {
        date date
        fk supplier
        enum payment "contado|credito"
        fk account
        decimal subtotal
        decimal tax "ITBIS pagado"
        decimal total
        uuid client_uuid
    }
    PurchaseLine {
        decimal qty
        decimal unit_cost "sin ITBIS"
    }
```

- `Commitment.frequency` suma **anual** con `due_month` (persona).
- `Transaction` suma `tax_amount` opcional (ITBIS pagado en un gasto con comprobante) para el
  resumen de ITBIS.

---

## 4. Servicios (funciones puras + cargadores)

```python
# business/services/inventory.py
weighted_average(stock, avg_cost, qty_in, unit_cost) -> Decimal
replay(movements: list[MovementInput]) -> StockState      # existencia, promedio y valor por fecha
register_purchase(ws, user, PurchaseData) -> Purchase      # entradas + movimiento o CxP; idempotente
register_adjustment(ws, user, product, qty, kind, on, note) -> InventoryMovement
inventory_snapshot(ws, on) -> list[ProductStock]           # existencia, promedio, valor, días de inventario
# sales.py: register_sale usa el promedio y crea la salida; edit_sale(ws, user, sale, SaleData)
# indicators.py: suma inventory_value, shrinkage (mermas), cogs_is_estimated por producto
# reports.py
monthly_statements(ws, months=6) -> list[MonthStatement]   # resultado y flujo por mes
tax_summary(ws, month) -> TaxSummary                       # ITBIS cobrado, pagado, estimado por pagar
export_csv(ws, start, end) -> bytes
# personal: annual commitments → provisión mensual en el plan y pago completo en su fecha
```

## 5. Alertas nuevas

- **existencia_baja**: un producto llegó a su mínimo (o menos).
- **existencia_negativa**: se vendió más de lo registrado → revisar compras o hacer un conteo.
- **inventario_quieto**: un producto con valor relevante no se vende hace 60 días (dinero parado).
- **pago_anual_cercano** (persona): un compromiso anual vence en los próximos 30 días y lo
  apartado no alcanza.

## 6. Pantallas

- **Inventario**: existencias y valor por producto, mínimo, alerta, "contar" (ajuste rápido),
  merma, historial del producto.
- **Registrar compra de mercancía** (botón +): proveedor, productos, cantidades y costos,
  contado/crédito, ITBIS pagado.
- **Venta**: aviso si no hay existencias suficientes; **Editar venta** (sin cobros).
- **Reportes**: últimos 6 meses (ventas, costo, ganancia, gastos, resultado y flujo), gráfico,
  resumen de ITBIS del mes, exportar CSV.
- **Inicio negocio**: valor del inventario y alerta de existencias.
- **Persona**: compromisos anuales en la bienvenida, en el plan ("apartar RD$X al mes para el
  marbete") y en próximos pagos.

## 7. Plan de la Fase 3 (pasos verificables)

| # | Paso | Verificación clave |
|---|---|---|
| C1 | Modelos de inventario y costo promedio (puro) | Promedio ponderado exacto; replay del historial = estado guardado |
| C2 | Compras de mercancía, inventario inicial, mermas y ajustes | Compra a crédito no mueve efectivo; merma es gasto; idempotencia |
| C3 | Ventas con inventario y edición de ventas | Costo de lo vendido = promedio; anular/editar revierte; vender sin existencias avisa |
| C4 | Indicadores: valor del inventario, mermas, días de inventario | Resultado y flujo separados también con inventario |
| C5 | Alertas de inventario y de pagos anuales | Un test por regla |
| C6 | Compromisos anuales en el plan personal | Provisión mensual + pago completo; el caso RD$50,000 no cambia |
| C7 | Resumen de ITBIS y reportes mensuales con exportación CSV | Cifras = suma de los indicadores de cada mes |
| C8 | Interfaz (inventario, compras, reportes, edición) y bienvenida (inventario inicial) | Tests de vistas + Chromium sin errores de CSP |
| C9 | Cierre: demo con un producto de reventa con inventario, seguridad y aislamiento, docs | `seed_demo` con inventario real; aislamiento cubre rutas nuevas |

## 8. Decisiones que necesito confirmar

1. **Inventario solo para productos que se compran y revenden** (o terminados comprados); los
   producidos con insumos siguen con costo por componentes hasta la Fase 4.
2. **Costo promedio ponderado** como método de costo.
3. **Vender sin existencias se permite**, con aviso y alerta (no se bloquea la venta).
4. **Mermas y ajustes negativos son gasto del mes** ("Mermas y ajustes"); no mueven efectivo.
5. **Compromisos anuales**: el plan personal aparta una provisión mensual (1/12) y el pago
   completo sale de lo apartado en su fecha.
6. **ITBIS**: resumen informativo (cobrado en ventas − pagado en compras y gastos con comprobante);
   no prepara declaraciones ante la DGII.
7. **Fuera de esta fase**: varias personas por negocio, varias monedas y recetas con insumos.

---

## 9. Cierre de la Fase 3: criterios y evidencia

| Criterio | Cómo se verifica |
|---|---|
| Costo promedio ponderado exacto; replay del historial = estado guardado | `apps/business/tests/test_inventory.py::test_promedio_ponderado`, `test_replay_del_historial`, `test_anular_compra_revierte_existencias` |
| Compra a crédito no mueve efectivo; compra no es gasto; idempotencia | `test_compra_a_credito_no_mueve_efectivo`, `test_inventario_inicial_compra_y_venta` (costo variable 0) |
| Merma es gasto del mes y no mueve efectivo; conteo físico | `test_mermas_ajustes_y_conteo` |
| Costo de lo vendido = promedio; anular/editar revierte; vender sin existencias avisa | `test_inventario_inicial_compra_y_venta`, `test_editar_venta`, `test_vender_sin_existencias_avisa_y_anular_revierte` |
| Valor y días de inventario; resultado y flujo separados | `test_inventario_inicial_compra_y_venta` (900 de valor, 39 días) y la demo (`test_seed_demo.py`) |
| Un test por regla de alerta nueva | `apps/alerts/tests/test_rules_business.py::test_alertas_de_inventario` (3 reglas), `test_rules.py::test_pago_anual_cercano`, `test_evaluate_business.py::test_alertas_de_inventario_desde_la_base` |
| Compromisos anuales: provisión mensual y el caso RD$50,000 no cambia | `apps/personal/tests/test_annual.py` y `TestCaso50000` intacto |
| Reportes = suma de los indicadores de cada mes; ITBIS; CSV | `apps/reports/tests/test_business_reports.py` |
| Interfaz sin errores de CSP | `apps/business/tests/test_views_fase3.py` y revisión en Chromium (390 × 844) de 12 pantallas nuevas o cambiadas: sin errores de consola ni de CSP; el gráfico dibuja sus barras |
| Demo con inventario real | `apps/core/tests/test_seed_demo.py` (40 unidades a RD$74.3692, merma RD$148.74, valor RD$2,974.77) y `test_seed_dates.py` |
| Aislamiento de las rutas nuevas | `tests/test_aislamiento.py` y `tests/test_aislamiento_negocio.py` |

Comandos: `make check` y `make e2e`.

**Fase 4** ([docs/fase4.md](fase4.md)): varias personas por negocio (roles), varias monedas,
recetas con insumos, ventas sin conexión y archivos de apoyo 606/607. Las declaraciones fiscales
siguen fuera de alcance.
