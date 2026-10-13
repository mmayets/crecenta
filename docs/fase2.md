# Fase 2 — Pequeños negocios: propuesta de diseño

> Para revisión **antes de escribir código**. Alcance del encargo (§5, §8, §11, §12, §14): perfil de
> negocio, productos y costos, ventas, CxC/CxP, separación del propietario, transferencias entre
> espacios, calculadora de precios y márgenes, plan de negocio con IA, alertas e inicio de negocio.
> Se mantiene el principio rector: **los números los calcula el código; la IA explica.**

---

## 1. Reglas contables (lo más importante a confirmar)

El encargo pide separar **ventas, ganancia y efectivo disponible**. Para una pequeña empresa sin
contador, propongo estas reglas simples y explicables:

| Concepto | Se calcula con | Nota |
|---|---|---|
| **Ventas** | Líneas de venta del período, **sin ITBIS**, al momento de vender (contado o crédito) | Una venta a crédito es venta el día que se hace, aunque no se haya cobrado. |
| **Costo de lo vendido** | Cantidad × **costo unitario guardado al vender** (`unit_cost_snapshot`) | Estimado: sin inventario hasta la Fase 3. Si cambia el costo del producto, las ventas pasadas no cambian. |
| **Ganancia bruta** | Ventas − costo de lo vendido | Margen bruto % = ganancia bruta / ventas. |
| **Gastos operativos** | Gastos registrados en categorías del grupo "gasto operativo" (alquiler del local, nómina, servicios, publicidad…) | |
| **Resultado operativo** | Ganancia bruta − gastos operativos | |
| **Flujo de efectivo** | Entradas y salidas **reales** de las cuentas del negocio | Separado de la ganancia: incluye cobros de ventas a crédito, compras de materiales, pagos a proveedores, préstamos y retiros del propietario. |
| **Dinero que puedes usar** | Efectivo del negocio − pagos comprometidos (CxP, nómina y gastos fijos hasta el próximo cobro esperado) − reserva operativa | Análogo a "Disponible para gastar" de la persona. |

Consecuencias de esas reglas (cómo se clasifica cada movimiento en el negocio):

| Movimiento | ¿Cuenta como venta / gasto del resultado? | ¿Mueve efectivo? |
|---|---|---|
| Venta de contado | Venta (por la línea de venta) | Sí, entrada |
| Venta a crédito | Venta (por la línea de venta) + crea una CxC | No, hasta cobrar |
| Cobro de una CxC (`cobro_cxc`, nuevo) | No (ya fue venta) | Sí, entrada |
| Compra de materiales / empaque (`compra_inventario`) | No (el costo entra por el costo unitario al vender) | Sí, salida |
| Comisión o entrega pagada (grupo "costo variable") | No (ya está en el costo unitario) | Sí, salida — se usa en la alerta de "costos creciendo más que las ventas" |
| Compra a crédito a proveedor | Crea una CxP | No, hasta pagar |
| Pago a proveedor (`pago_cxp`, nuevo) | No | Sí, salida |
| Gasto operativo (alquiler, nómina…) | Sí, gasto | Sí, salida |
| Préstamo recibido / cuota pagada | No (solo efectivo) | Sí |
| Aporte del propietario (`aporte_propietario`, nuevo) | No | Sí, entrada |
| Retiro del propietario (`retiro_propietario`, nuevo) | No es gasto del negocio | Sí, salida |

**ITBIS**: si el negocio vende con ITBIS, las ventas se muestran **sin** el impuesto y el ITBIS
cobrado se acumula como "ITBIS por pagar" (informativo; no se preparan declaraciones).

---

## 2. Transferencias entre espacios (persona ↔ negocio)

`WorkspaceTransfer(from_ws, to_ws, amount, date, kind[aporte|retiro_propietario], note)` crea dos
movimientos espejo en una transacción, cada uno en su espacio, con un `client_uuid` común derivado:

| Tipo | En el negocio | En la persona |
|---|---|---|
| **Retiro del propietario** | Salida `retiro_propietario` (categoría "Retiros del propietario") | Entrada **ingreso** (categoría nueva "Retiros de mi negocio") — es dinero que la persona recibe para vivir |
| **Aporte** | Entrada `aporte_propietario` (categoría "Aportes del propietario") | Salida neutra (no es gasto de consumo; categoría "Aporte a mi negocio") |

Solo se puede transferir entre espacios de los que la persona es **propietaria**. Antes de un retiro,
el sistema calcula la **reserva operativa** y avisa: *"El negocio tiene RD$40,000 en efectivo, pero
necesita RD$32,000 para los compromisos registrados. Puedes retirar hasta RD$8,000 sin dejar pagos
sin cubrir."* El retiro se puede hacer igual (la persona decide), pero queda una alerta.

---

## 3. Modelos nuevos

```mermaid
erDiagram
    Workspace ||--o| BusinessProfile : ""
    Workspace ||--o{ Product : ""
    Product ||--o{ CostComponent : "costo unitario = suma"
    Workspace ||--o{ OperatingExpense : ""
    Workspace ||--o| BusinessGoal : ""
    Workspace ||--o{ Customer : ""
    Workspace ||--o{ Supplier : ""
    Workspace ||--o{ Sale : ""
    Sale ||--o{ SaleLine : ""
    Product ||--o{ SaleLine : ""
    Sale |o--o| Receivable : "si es a crédito"
    Receivable ||--o{ Transaction : "cobros"
    Workspace ||--o{ Payable : ""
    Payable ||--o{ Transaction : "pagos"
    Workspace ||--o{ WorkspaceTransfer : "from/to"
    WorkspaceTransfer ||--|| Transaction : "salida"
    WorkspaceTransfer ||--|| Transaction : "entrada"

    BusinessProfile {
        string activity
        enum model "productos|servicios|mixto"
        decimal tax_rate_itbis "0.18"
        bool prices_include_tax
        int hours_available_month "capacidad (servicios)"
    }
    Product {
        string name
        decimal price
        decimal unit_cost "derivado de componentes o manual"
        bool is_service
        int labor_minutes
        decimal expected_monthly_units "para el plan"
    }
    CostComponent {
        enum type "materia|empaque|comision_pct|entrega|mano_obra"
        decimal amount_or_pct
    }
    OperatingExpense {
        string name
        decimal amount
        enum frequency "mensual|quincenal|semanal"
        int due_day
        fk category
    }
    BusinessGoal {
        decimal target_sales
        decimal target_margin_pct
        decimal target_profit
        decimal cash_reserve
    }
    Sale {
        date date
        enum payment "contado|credito"
        fk customer
        fk account "contado"
        uuid client_uuid
        decimal subtotal
        decimal tax
        decimal total
    }
    SaleLine {
        decimal qty
        decimal unit_price
        decimal discount_pct
        decimal unit_cost_snapshot
    }
    Receivable {
        decimal amount
        decimal paid
        date due_date
        enum status "pendiente|parcial|pagada|vencida"
    }
    Payable {
        fk supplier
        string concept
        decimal amount
        decimal paid
        date due_date
        enum status
    }
    WorkspaceTransfer {
        enum kind "aporte|retiro_propietario"
        decimal amount
        date date
    }
```

`ledger.TxKind` suma `cobro_cxc`, `pago_cxp`, `aporte_propietario` y `retiro_propietario`, todos
neutros para el resultado. `Transaction` gana `sale`, `receivable` y `payable` (FK opcionales).

---

## 4. Servicios (funciones puras + cargadores), con firmas

### pricing/services/ (motor de precios, encargo §8)
```python
price_from_margin(cost, margin) -> PriceResult                 # ya existe: 600 al 30 % = 857.14
price_from_markup(cost, markup) -> PriceResult                 # ya existe
@dataclass PricingInputs: unit_cost, commission_pct, discount_pct, delivery_cost, tax_rate,
                          prices_include_tax, target_margin
compute_price(inputs) -> PricingResult        # precio sugerido con comisión e ITBIS, supuestos
minimum_price(inputs) -> Decimal              # cubre costos y comisión (margen 0)
margin_after_discount(price, cost, discount_pct, commission_pct) -> Decimal
break_even_units(fixed_costs, unit_price, unit_variable_cost) -> Decimal | None
supplier_increase(inputs, increase_pct) -> SensitivityResult   # nuevo costo, margen y precio para mantenerlo
volume_margin_matrix(products: list[ProductStats]) -> list[MatrixCell]  # "vende mucho y deja poco"
service_capacity(labor_minutes, hours_available, price) -> CapacityResult  # techo de ingresos
```

### business/services/
```python
unit_cost(product) -> Decimal                                  # suma de componentes (comisión % sobre precio)
register_sale(ws, user, SaleData) -> Sale                      # contado → movimiento venta; crédito → CxC; idempotente
collect_receivable(ws, user, receivable, amount, account, on) -> Transaction   # cobro parcial o total
register_payable(ws, user, PayableData) -> Payable
pay_payable(ws, user, payable, amount, account, on) -> Transaction
@dataclass PeriodIndicators: sales, cogs, gross_profit, gross_margin_pct, operating_expenses,
    operating_result, cash_in, cash_out, net_cash_flow, tax_collected, receivables, payables,
    by_product: list[ProductMargin], break_even_units, goal_progress
compute_indicators(inputs: BusinessPeriodInputs) -> PeriodIndicators     # puro
load_business_inputs(ws, period) -> BusinessPeriodInputs                 # ORM
cash_risk(cash_now, receivables, payables, expenses, horizon) -> list[CashGap]  # por fechas
operating_reserve(ws, today) -> ReserveResult       # efectivo, compromisos, retiro máximo seguro
```

### workspaces/services/transfers.py
```python
transfer_between(user, from_ws, to_ws, amount, on, kind, from_account, to_account, note) -> WorkspaceTransfer
```

### planning (plan de negocio)
```python
build_business_plan(inputs: BusinessPlanInputs) -> BusinessPlanResult
#   volumen esperado por producto → ventas, costo, ganancia bruta, gastos operativos, resultado;
#   equilibrio; ventas necesarias para la utilidad objetivo; flujo por fechas (CxC/CxP/gastos);
#   retiro máximo del propietario; alternativas por reglas (subir precio al margen objetivo,
#   bajar costo de un componente, vender más del producto con mejor margen, reducir gasto
#   reducible, posponer retiro) — cada una recalculada por el motor.
request_business_plan(ws, user, today) -> PlanVersion          # mismo flujo y estados que el personal
```
La IA usa una plantilla nueva `plan_negocio.v1.md` con el **mismo verificador de cifras** y la
misma narrativa por reglas como respaldo.

### alerts (negocio)
```python
evaluate_business(ctx) -> list[AlertDraft]
#   margen_bajo_objetivo, costos_variables_crecen, riesgo_caja_fechas, retiro_sin_cobertura
```

---

## 5. Pantallas (negocio)

- **Inicio negocio**: las cuatro tarjetas (¿Cuánto vendí? ¿Cuánto me costó vender? ¿Cuánto gané?
  ¿Cuánto dinero puedo utilizar?), CxC y CxP con vencimientos, productos ordenados por margen,
  alertas, avance de objetivos.
- **Registrar** (botón +): venta, gasto, compra, cobro, pago a proveedor, retiro o aporte del
  propietario.
- **Ventas**: lista del período, detalle, venta rápida (producto, cantidad, contado/crédito).
- **Productos y costos**: componentes de costo, precio actual vs. sugerido, margen real.
- **Calculadora de precios**: interactiva (Alpine), el cálculo lo hace el servidor (htmx); muestra
  supuestos, margen vs. recargo, precio mínimo, margen tras descuento, equilibrio y sensibilidad.
- **Por cobrar / por pagar**: vencimientos, cobro/pago parcial.
- **Propietario**: retiros y aportes con el aviso de reserva operativa.
- **Plan de negocio**: igual que el personal (versiones, aceptar/editar/descartar, alternativas).
- Navegación inferior: Inicio · Ventas · **+** · Precios · Alertas.

---

## 6. Plan de la Fase 2 (pasos verificables)

Cada paso cierra con `make check` (ruff, mypy, pytest con cobertura ≥ 90 % en `services/`,
`check --deploy`) y commit.

| # | Paso | Verificación clave |
|---|---|---|
| B1 | Modelos de negocio, nuevos tipos de movimiento y su clasificación | Cobros, pagos de CxP, aportes y retiros no cuentan como venta ni gasto |
| B2 | Motor de precios completo | 600 al 30 % = 857.14; precio mínimo; margen tras descuento; equilibrio; sensibilidad; matriz volumen-margen; capacidad de servicios |
| B3 | Ventas, CxC y CxP (contado/crédito, cobros y pagos parciales, idempotentes) | Venta a crédito no mueve efectivo hasta cobrarse; doble envío no duplica |
| B4 | Indicadores del período, riesgo de caja por fechas y reserva operativa | Ventas, costo, ganancia y flujo separados; caso "RD$40,000 vs RD$32,000" |
| B5 | Transferencias persona ↔ negocio | Movimientos espejo; solo propietario; aviso de reserva antes del retiro |
| B6 | Plan de negocio con IA | Ninguna cifra de la narrativa difiere del motor; alternativas recalculadas |
| B7 | Alertas de negocio | Un test por regla |
| B8 | Onboarding de negocio (wizard + conversacional) | Datos mínimos → primer plan de negocio |
| B9 | Interfaz de negocio | Tests de vistas + revisión en Chromium (sin errores de CSP) |
| B10 | Cierre: demo ampliada (ventas de Dulces Ana), seguridad, documentación | `seed_demo` con indicadores reales; aislamiento cubre todas las rutas nuevas |

---

## 7. Decisiones que necesito confirmar

1. **Ventas a crédito** cuentan como venta el día que se hacen; el efectivo entra al cobrar.
2. **Costo de lo vendido** = costo unitario guardado al vender (sin inventario hasta la Fase 3).
   Comisiones y entregas configuradas en el producto ya están en ese costo; si además se pagan como
   movimiento, ese movimiento solo cuenta para el flujo de efectivo.
3. **Retiro del propietario** = ingreso en el espacio personal ("Retiros de mi negocio");
   **aporte** = salida neutra en lo personal.
4. **ITBIS**: ventas sin ITBIS e "ITBIS por pagar" informativo.
5. **Período de análisis**: mensual por calendario (del 1 al último día) para el negocio.
