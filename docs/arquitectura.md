# Crecenta — Propuesta de arquitectura (Fase 1)

> Documento para revisión **antes de escribir código**. Contiene: árbol del proyecto,
> diagrama de modelos, servicios con sus firmas y el plan de la Fase 1 en pasos verificables.
> Las decisiones no especificadas en el encargo están en [`decisiones.md`](decisiones.md).

---

## 1. Árbol del proyecto

```
crecenta/
├── scripts/build_icons.py         # genera el sprite SVG de íconos
├── docker-compose.yml              # web, db (postgres:16), redis, worker, beat
├── Dockerfile                      # python:3.12-slim + Tailwind CLI standalone (stage de build)
├── .env.example
├── pyproject.toml                  # dependencias, ruff, mypy, pytest, coverage
├── manage.py
├── tailwind.config.js
├── config/
│   ├── __init__.py                 # carga la app de Celery
│   ├── celery.py
│   ├── urls.py
│   ├── wsgi.py / asgi.py
│   └── settings/
│       ├── base.py
│       ├── dev.py
│       ├── prod.py
│       └── test.py                 # CELERY_TASK_ALWAYS_EAGER, proveedor IA falso
├── apps/
│   ├── core/
│   │   ├── money.py                # Decimal, cuantización ROUND_HALF_UP, formato RD$/US$
│   │   ├── dates.py                # días reales del mes, días hábiles seleccionados, próximos N días
│   │   ├── periods.py              # períodos por fecha de cobro (mensual/quincenal/semanal)
│   │   ├── ratelimit.py            # limitador simple sobre la caché (Redis)
│   │   ├── models.py               # UUIDModel, TimeStampedModel
│   │   ├── templatetags/icons.py   # {% icon "nombre" %} → <svg><use href="#i-nombre"></svg>
│   │   └── middleware.py           # cabeceras de seguridad adicionales (CSP, Permissions-Policy)
│   ├── accounts/                   # User (email como login), consentimiento de IA, exportar/eliminar
│   ├── workspaces/
│   │   ├── models.py               # Workspace, Membership, WorkspaceTransfer
│   │   ├── managers.py             # WorkspaceScopedQuerySet.for_workspace()
│   │   ├── mixins.py               # WorkspaceRequiredMixin (resuelve /e/<uuid>/ y valida membresía)
│   │   └── services/transfers.py
│   ├── onboarding/
│   │   ├── services/completeness.py
│   │   ├── services/conversational.py
│   │   ├── views.py                # wizard HTMX (un paso = un partial)
│   │   └── templates/onboarding/
│   ├── ledger/
│   │   ├── models.py               # Account, Category, Transaction
│   │   ├── services/balances.py
│   │   ├── services/classification.py   # qué cuenta como gasto/ingreso
│   │   ├── services/sync.py        # alta idempotente por client_uuid (offline)
│   │   ├── services/quick_entry.py # texto libre / voz → borrador de movimiento
│   │   └── system_categories.py     # catálogo de categorías del sistema
│   ├── personal/
│   │   ├── models.py               # IncomeSource, Commitment, Debt, SavingsGoal, Preference, BudgetPeriod, BudgetLine
│   │   └── services/
│   │       ├── budget_engine.py    # plan determinístico del período
│   │       ├── cash_timeline.py    # viabilidad por fechas
│   │       ├── alternatives.py     # alternativas por reglas cuando no es viable
│   │       ├── savings.py          # aportes diarios/semanales/… con días reales
│   │       └── availability.py     # "Disponible en cuentas" vs "Disponible para gastar"
│   ├── business/                   # Fase 1: solo modelos mínimos (BusinessProfile, Product) para seed_demo
│   ├── pricing/
│   │   └── services/margins.py     # Fase 1: funciones puras precio por margen / markup (con tests)
│   ├── planning/
│   │   ├── models.py               # PlanVersion
│   │   ├── services/snapshot.py    # inputs_snapshot anonimizado
│   │   ├── services/missing_data.py
│   │   ├── services/generate_plan.py
│   │   ├── services/lifecycle.py   # aceptar / editar / descartar
│   │   └── tasks.py
│   ├── alerts/
│   │   ├── models.py               # AlertRule, Alert
│   │   ├── services/rules_personal.py
│   │   ├── services/evaluate.py
│   │   └── tasks.py                # beat diario + disparo tras movimiento confirmado
│   ├── receipts/
│   │   ├── models.py               # Receipt
│   │   ├── services/ingest.py      # sha256 + detección de duplicados
│   │   ├── services/ocr.py
│   │   ├── views.py                # revisión + descarga autenticada
│   │   └── tasks.py
│   ├── ai/
│   │   ├── providers/base.py       # interfaz AIProvider, Attachment, ProviderError
│   │   ├── providers/gemini_provider.py
│   │   ├── providers/openai_provider.py
│   │   ├── providers/fake.py       # determinístico, para tests y desarrollo sin claves
│   │   ├── schemas.py              # Pydantic: PlanNarrative, OnboardingExtraction, ReceiptExtraction, QuickEntry
│   │   ├── services/client.py      # consentimiento → límite → llamar → validar → 1 reintento → reglas
│   │   ├── services/guards.py      # verificación de cifras de la narrativa contra el motor
│   │   ├── services/fallback.py    # narrativa genérica basada en reglas
│   │   ├── services/prompts.py     # carga y render de plantillas versionadas
│   │   ├── models.py               # AIInteraction
│   │   └── prompts/
│   │       ├── plan_personal.v1.md
│   │       ├── onboarding_extraccion.v1.md
│   │       ├── comprobante_ocr.v1.md
│   │       └── registro_rapido.v1.md
│   ├── reports/                    # Fase 1: tablero de inicio persona (services/dashboard.py)
│   └── pwa/
│       ├── views.py                # manifest, service worker (servido en / para su scope), offline
│       └── templates/pwa/
├── templates/
│   ├── base.html                   # layout mobile-first, barra inferior, botón flotante "+ Registrar"
│   ├── partials/
│   └── icons/sprite.svg            # íconos SVG (set Lucide, licencia ISC)
├── static/
│   ├── src/app.css                 # entrada Tailwind
│   ├── css/app.css                 # compilado
│   ├── js/
│   │   ├── offline-queue.js        # IndexedDB + sincronización
│   │   └── app.js
│   ├── vendor/                     # htmx, alpine, apexcharts (servidos localmente, versión fijada)
│   └── icons/                      # íconos PWA 192/512/maskable
├── tests/                          # tests transversales (aislamiento, e2e de flujos)
└── docs/
    ├── arquitectura.md
    └── decisiones.md
```

Cada app tiene además `tests/` con `factories.py` (factory_boy).

---

## 2. Diagrama de modelos

```mermaid
erDiagram
    User ||--o{ Membership : tiene
    Workspace ||--o{ Membership : agrupa
    User ||--o{ Workspace : "owner"
    Workspace ||--o{ WorkspaceTransfer : "from/to"

    Workspace ||--o{ Account : ""
    Workspace ||--o{ Category : ""
    Workspace ||--o{ Transaction : ""
    Account ||--o{ Transaction : ""
    Category ||--o{ Transaction : ""
    Receipt |o--o| Transaction : "comprobante"

    Workspace ||--o{ IncomeSource : ""
    Workspace ||--o{ Commitment : ""
    Workspace ||--o{ Debt : ""
    Workspace ||--o{ SavingsGoal : ""
    Workspace ||--o{ Preference : ""
    Category ||--o{ Commitment : ""
    Category ||--o{ Preference : ""
    Workspace ||--o{ BudgetPeriod : ""
    BudgetPeriod ||--o{ BudgetLine : ""
    Category ||--o{ BudgetLine : ""

    Workspace ||--o{ PlanVersion : ""
    PlanVersion |o--o{ BudgetPeriod : "origina"
    Workspace ||--o{ AlertRule : ""
    Workspace ||--o{ Alert : ""
    Workspace ||--o{ Receipt : ""
    Workspace ||--o{ AIInteraction : ""

    Workspace ||--o| BusinessProfile : "solo kind=business"
    Workspace ||--o{ Product : ""

    User {
        uuid id
        string email
        bool ai_consent
        datetime ai_consent_at
    }
    Workspace {
        uuid id
        fk owner
        enum kind "personal|business"
        string name
        enum currency "DOP|USD"
    }
    Membership {
        fk user
        fk workspace
        enum role "owner"
    }
    WorkspaceTransfer {
        fk from_ws
        fk to_ws
        decimal amount
        date date
        enum kind "aporte|retiro_propietario"
        fk out_tx
        fk in_tx
    }
    Account {
        string name
        enum type "efectivo|banco|tarjeta|billetera"
        enum currency
        decimal opening_balance
    }
    Category {
        string name
        enum group
        bool is_system
    }
    Transaction {
        uuid id
        date date
        decimal amount "siempre > 0"
        enum direction "in|out"
        enum kind
        enum status "confirmado|pendiente_revision"
        enum source "manual|voz|texto|comprobante|offline"
        uuid client_uuid "unique por workspace"
        fk transfer_pair "nullable"
    }
    IncomeSource {
        decimal net_amount
        enum frequency
        int_array pay_days
    }
    Commitment {
        decimal amount
        enum frequency
        int due_day
        bool is_fixed
    }
    Debt {
        decimal installment
        decimal balance
        int due_day
        decimal interest_rate "nullable"
        date end_date "nullable"
    }
    SavingsGoal {
        string purpose
        decimal target_amount
        decimal contribution_amount
        enum contribution_frequency
        enum daily_mode
        int_array selected_weekdays
        date deadline "nullable"
    }
    BudgetPeriod {
        date start
        date end
        date pay_event
    }
    BudgetLine {
        decimal assigned
        enum kind "compromiso|deuda|esencial|ahorro|discrecional|reserva"
        date due_date "nullable"
    }
    PlanVersion {
        enum kind
        enum status "propuesta|aceptado|descartado|reemplazado"
        json inputs_snapshot
        json computed
        json ai_narrative
        json assumptions
        json missing_data
        datetime accepted_at
    }
    Alert {
        string code
        enum severity
        json data_used
        bool is_projection
        enum status
        json suggested_action
        string dedupe_key
    }
    Receipt {
        string sha256
        enum status
        json extracted
        json field_confidence
    }
    AIInteraction {
        string purpose
        string provider
        string model
        int prompt_tokens
        int completion_tokens
        int latency_ms
        bool schema_valid
    }
```

Notas:
- Todas las tablas de dominio heredan `UUIDModel` (PK UUID) y llevan `workspace` FK + índice.
- Montos: `DecimalField(max_digits=14, decimal_places=2)`, `CheckConstraint(amount > 0)` y el signo lo da `direction`.
- `Transaction(workspace, client_uuid)` con `UniqueConstraint` (condicional a `client_uuid IS NOT NULL`) → idempotencia offline.
- `Receipt(workspace, sha256)` indexado (no único: el duplicado se guarda marcado para que el usuario decida).
- `Alert.dedupe_key` + estado evita repetir la misma alerta cada día.

---

## 3. Servicios y firmas

Convención: funciones puras que reciben dataclasses de entrada (`frozen=True`) y devuelven
dataclasses de resultado. Los *loaders* (`load_*_inputs(workspace)`) son la única parte que toca el ORM.

### core
```python
# money.py
D = Decimal
def q(value: Decimal) -> Decimal                                    # ROUND_HALF_UP a 0.01
def to_money(value: str | int | Decimal) -> Decimal                  # rechaza float
def fmt(value: Decimal, currency: str = "DOP") -> str                # "RD$50,000.00" / "US$…"
def split_evenly(total: Decimal, parts: int) -> list[Decimal]        # el centavo sobrante va a la última parte

# dates.py
def days_in_month(year: int, month: int) -> int
def count_weekdays(start: date, end: date, weekdays: set[int]) -> int
def clamp_day(year: int, month: int, day: int) -> date               # día 31 → último día del mes

# periods.py
@dataclass(frozen=True)
class PayEvent: date: date; amount: Decimal; source_id: UUID
def pay_events(sources: list[IncomeInput], start: date, end: date) -> list[PayEvent]
def period_for(sources: list[IncomeInput], today: date) -> Period   # [cobro actual, día antes del próximo ciclo mensual]
```

### workspaces
```python
def create_workspaces_for_usage(user: User, usage: Literal["persona","negocio","ambos"]) -> list[Workspace]
def user_workspaces(user: User) -> QuerySet[Workspace]
def transfer_between(from_ws: Workspace, to_ws: Workspace, amount: Decimal, on: date,
                     kind: str, from_account: Account, to_account: Account, note: str = "") -> WorkspaceTransfer
```

### ledger
```python
# classification.py
def counts_as_expense(tx: TxLike) -> bool      # False para transferencia_interna, retiro_efectivo, pago_deuda (va a deuda), etc.
def counts_as_income(tx: TxLike) -> bool       # False para préstamo y transferencia_interna
# balances.py
def account_balance(account: Account, as_of: date | None = None) -> Decimal
def total_balance(workspace: Workspace, as_of: date | None = None) -> Decimal
def spent_by_category(workspace: Workspace, start: date, end: date) -> dict[UUID, Decimal]
# sync.py
@dataclass(frozen=True)
class SyncResult: transaction: Transaction; created: bool
def upsert_from_client(workspace: Workspace, user: User, payload: QuickTxPayload) -> SyncResult
# quick_entry.py
def parse_free_text(workspace: Workspace, text: str) -> QuickEntryDraft          # IA → borrador, nunca persiste
def transcribe_and_parse(workspace: Workspace, audio: UploadedFile) -> QuickEntryDraft
def confirm_draft(workspace: Workspace, draft: QuickEntryDraft, edits: dict) -> Transaction
```

### personal
```python
# budget_engine.py
@dataclass(frozen=True)
class PersonalInputs:
    period: Period
    incomes: list[IncomeInput]
    commitments: list[CommitmentInput]
    debts: list[DebtInput]
    essentials: list[EssentialInput]          # estimado o promedio de historial
    savings: list[SavingsInput]
    discretionary_wish: Decimal | None        # "ocio" deseado por el usuario
    reserve_pct: Decimal = Decimal("0.10")    # sobre esenciales variables
    preferences: dict[UUID, Literal["prioritario","reducible"]]
    opening_cash: Decimal                     # saldo disponible al inicio del período

@dataclass(frozen=True)
class BudgetResult:
    period: Period
    income_total: Decimal
    lines: list[PlanLine]                     # categoría, grupo, monto, fecha, evento de cobro asignado
    totals_by_group: dict[str, Decimal]
    remaining: Decimal                        # ≥ 0 si viable
    viable: bool
    status: Literal["viable","ajustado","no_viable"]
    shortfalls: list[Shortfall]               # (fecha, compromiso, monto faltante)
    alternatives: list[Alternative]           # vacío si viable
    by_pay_event: list[PayEventAllocation]    # p. ej. ahorro 3,500 por quincena
    assumptions: list[str]

def build_personal_plan(inputs: PersonalInputs) -> BudgetResult
def load_personal_inputs(workspace: Workspace, today: date) -> PersonalInputs

# cash_timeline.py
@dataclass(frozen=True)
class TimelineEvent: date: date; delta: Decimal; label: str; ref: str
def build_timeline(opening_cash: Decimal, pay_events: list[PayEvent], outflows: list[ScheduledOutflow]) -> list[TimelinePoint]
def find_shortfalls(points: list[TimelinePoint]) -> list[Shortfall]

# alternatives.py
def generate_alternatives(inputs: PersonalInputs, result: BudgetResult) -> list[Alternative]
#   reglas: reducir_discrecional, bajar_ahorro, aplazar_ahorro, repartir_entre_cobros, usar_reserva
#   cada alternativa se recalcula con build_personal_plan y trae su impacto y viabilidad resultante

# savings.py
def contributions_in_period(goal: SavingsInput, start: date, end: date) -> Decimal
def contributions_per_pay_event(goal: SavingsInput, events: list[PayEvent], period: Period) -> list[Decimal]
def goal_progress(goal: SavingsGoal, today: date) -> GoalProgress     # aportado, esperado a la fecha, en riesgo

# availability.py
@dataclass(frozen=True)
class Availability:
    in_accounts: Decimal                  # suma de saldos
    pending_commitments: Decimal
    pending_savings: Decimal
    reserves: Decimal
    spendable: Decimal                    # in_accounts − pendientes − reservas (puede ser negativo; se muestra con advertencia)
def compute_availability(workspace: Workspace, today: date) -> Availability
```

### pricing (Fase 1: solo funciones puras)
```python
def price_from_margin(cost: Decimal, margin: Decimal) -> PriceResult      # 600, 0.30 → 857.14
def price_from_markup(cost: Decimal, markup: Decimal) -> PriceResult
def margin_vs_markup(cost: Decimal, price: Decimal) -> tuple[Decimal, Decimal]
```

### planning
```python
def build_snapshot(workspace: Workspace, today: date) -> dict                 # sin nombres ni números de cuenta
def compute_missing_data(inputs: PersonalInputs, workspace: Workspace) -> list[MissingItem]
def generate_personal_plan(workspace_id: UUID, today: date | None = None) -> PlanVersion   # tarea Celery
def accept_plan(plan: PlanVersion, user: User, edits: dict | None = None) -> PlanVersion   # crea BudgetPeriod/BudgetLine, reemplaza anterior
def discard_plan(plan: PlanVersion, user: User) -> PlanVersion
def recalc_with_edits(plan: PlanVersion, edits: dict) -> BudgetResult          # el motor recalcula toda edición
```

### ai
```python
class AIProvider(Protocol):
    name: str
    def generate_json(self, *, system: str, user: str, schema: type[BaseModel],
                      images: list[bytes] | None = None) -> ProviderResponse
    def transcribe(self, audio: bytes, mime: str) -> ProviderResponse

def get_provider() -> AIProvider                                  # AI_PROVIDER=gemini|openai|fake
def run_structured(workspace: Workspace, purpose: str, prompt_name: str, context: dict,
                   schema: type[T], fallback: Callable[[], T], images=None) -> AIResult[T]
#   llama → valida Pydantic → 1 reintento → fallback; registra AIInteraction; respeta consentimiento y rate limit
def render_prompt(name: str, context: dict) -> tuple[str, str]   # lee ai/prompts/<name>.vN.md
def allowed_amounts(computed: dict, alternatives: list[dict]) -> set[Decimal]
def verify_narrative(narrative: PlanNarrative, allowed: set[Decimal]) -> GuardResult   # extrae cifras y compara
def fallback_narrative(result: BudgetResult, missing: list[MissingItem]) -> PlanNarrative
```

### alerts
```python
def evaluate_personal(workspace: Workspace, today: date) -> list[AlertDraft]   # puro sobre datos cargados
def persist_alerts(workspace: Workspace, drafts: list[AlertDraft]) -> list[Alert]  # dedupe por dedupe_key
def check_purchase_impact(workspace: Workspace, amount: Decimal, category: Category, on: date) -> list[AlertDraft]
# reglas: categoria_80, riesgo_fin_periodo (proyección lineal solo esenciales variables),
#         pago_sin_cobertura (N días), meta_en_riesgo, compra_afecta_reserva, buen_desempeno
```

### receipts
```python
def ingest_receipt(workspace: Workspace, file: UploadedFile) -> Receipt        # calcula sha256, encola OCR
def find_duplicates(receipt: Receipt) -> list[Receipt | Transaction]           # sha256 o comercio+total+fecha±1
def run_ocr(receipt_id: UUID) -> Receipt                                       # tarea Celery
def confirm_receipt(receipt: Receipt, data: ReceiptConfirmForm) -> Transaction
```

### onboarding
```python
def completeness(workspace: Workspace) -> Completeness           # % y lista de faltantes con su efecto en el plan
def minimum_ready(workspace: Workspace) -> bool                  # ingreso + al menos compromisos/esenciales declarados
def extract_from_text(workspace: Workspace, text: str) -> OnboardingExtraction    # IA, no persiste
def apply_extraction(workspace: Workspace, confirmed: OnboardingExtraction) -> None
```

---

## 4. Plan de la Fase 1 (pasos verificables)

Al cierre de cada paso: `ruff check .`, `ruff format --check .`, `pytest`, y
`DJANGO_SETTINGS_MODULE=config.settings.prod python manage.py check --deploy` (con variables de prod de prueba). Se reporta el resultado y se hace commit.

| # | Paso | Entregable | Verificación |
|---|------|-----------|--------------|
| 1 | **Esqueleto** | `pyproject`, settings base/dev/prod/test, Docker + compose, Celery, `core` (money, dates, periods), `accounts.User` por email, allauth | `check`, `check --deploy`, tests de `core` (redondeo, días del mes, eventos de cobro quincenal 15/30 en febrero) |
| 2 | **Espacios y aislamiento** | `Workspace`, `Membership`, `WorkspaceScopedQuerySet`, `WorkspaceRequiredMixin`, rutas `/e/<uuid>/…` | Tests: usuario B recibe 404 en vistas/endpoints del espacio de A |
| 3 | **Ledger** | `Account`, `Category` (+ categorías del sistema), `Transaction`, saldos, clasificación, sync idempotente | Transferencia/retiro/préstamo no cuentan como gasto/ingreso; mismo `client_uuid` dos veces → 1 movimiento |
| 4 | **Motor personal** | `budget_engine`, `cash_timeline`, `alternatives`, `savings`, `availability` + modelos `personal` | Caso RD$50,000 exacto; variante quincenal (ahorro 3,500 × 2); caso no viable con faltante, fecha y ≥ 2 alternativas recalculadas; meta diaria con días reales y días seleccionados; disponible para gastar excluye comprometido. Cobertura ≥ 90 % |
| 5 | **Capa IA** | Proveedores Gemini/OpenAI/Fake, esquemas Pydantic, prompts versionados, `AIInteraction`, reintento + degradación, `verify_narrative` | Test: narrativa con cifra inventada se rechaza/degrada; JSON inválido → reintento → fallback; sin consentimiento no se llama |
| 6 | **Planificación** | `PlanVersion`, snapshot anonimizado, `missing_data`, tarea de generación, aceptar/editar/descartar | Snapshot no contiene nombres de cuenta; aceptar crea `BudgetLine` y marca anterior `reemplazado`; edición se recalcula en motor |
| 7 | **Alertas** | Reglas personales, evaluación diaria (beat) y tras movimiento, dedupe | Un test por regla; compromisos fijos no se proyectan linealmente |
| 8 | **Comprobantes** | Carga, sha256, OCR asíncrono, revisión con campos dudosos, duplicados, descarga autenticada | Mismo archivo dos veces → `duplicado_sospechoso`; otro usuario no puede descargarlo |
| 9 | **Onboarding** | Paso 0 (persona/negocio/ambos), wizard HTMX con guardado por paso, barra de completitud, modo conversacional con tabla editable | Test de flujo mínimo → plan generado; extracción no persiste hasta confirmar |
| 10 | **UI** | Layout mobile-first, sprite SVG, inicio persona (dos cifras, barras por grupo, próximos pagos, meta, alertas), movimientos, registro rápido (manual/texto/voz/foto), plan (actual, historial, comparación), alertas, configuración y privacidad (consentimiento, exportar ZIP, eliminar cuenta) | Tests de vistas (200/permisos), test de exportación y eliminación |
| 11 | **PWA** | `manifest.webmanifest`, service worker (cache-first estáticos, network-first HTML, offline), cola IndexedDB + Background Sync + reintento al reconectar | Test del endpoint de sync; prueba Playwright (Chromium) en modo offline → reconexión → 1 solo movimiento |
| 12 | **Cierre** | `seed_demo` (persona RD$50,000 + negocio con producto de costo RD$600), docs, revisión de seguridad, cobertura | `seed_demo` idempotente; cobertura de `services/` ≥ 90 %; `check --deploy` sin avisos |

### Criterios de aceptación → dónde se prueban
- PWA instalable + gasto offline sin duplicar → pasos 3 y 11.
- Onboarding mínimo < 5 min con plan viable/ajustado/no viable → pasos 6 y 9 (3 pantallas mínimas).
- Caso RD$50,000 exacto; no viable con faltante, fecha y ≥ 2 alternativas → paso 4.
- Disponible para gastar sin comprometido; transferencias/retiros no son gasto → pasos 3 y 4.
- Comprobante repetido → duplicado sospechoso → paso 8.
- Ninguna cifra de la IA difiere del motor → paso 5 (`verify_narrative`) y paso 6 (test end-to-end con proveedor falso que intenta inventar cifras).
- Cobertura ≥ 90 % en `services/` → `--cov-fail-under=90` sobre `apps/*/services`.
