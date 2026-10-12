# Fase 1 — criterios de aceptación y evidencia

| Criterio (encargo §16) | Cómo se verifica |
|---|---|
| La app se instala como PWA en Android/iOS | Manifest `standalone` con íconos 192/512/maskable, service worker en `/`, metas de Apple. Chrome no reporta errores de instalabilidad (`Page.getInstallabilityErrors`). Tests: `apps/pwa/tests/test_pwa.py`. |
| Registrar un gasto sin conexión que se sincroniza al reconectar sin duplicarse | `make e2e` (Chromium): dos gastos sin red → reconexión → cola vacía → reenvío forzado → cada gasto aparece una vez. Idempotencia en el servidor: `apps/ledger/tests/test_sync.py`. |
| Onboarding mínimo en menos de 5 minutos con plan viable/ajustado/no viable | Tres formularios (ingresos, compromisos, esenciales) → "Generar mi plan": `apps/onboarding/tests/test_wizard.py::test_onboarding_minimo_hasta_el_plan`. Alternativa conversacional con tabla editable. |
| El plan del caso RD$50,000 coincide exactamente | `apps/personal/tests/test_budget_engine.py::TestCaso50000` (20,000 / 15,000 / 7,000 / 5,000 / 3,000 = 50,000, viable) y variante quincenal (3,500 por quincena). También `seed_demo`. |
| Un caso no viable muestra el faltante, la fecha y al menos dos alternativas recalculadas | `TestNoViable::test_faltante_total_fecha_y_alternativas` (faltante RD$2,000, 27 de octubre, bajar/aplazar ahorro recalculadas) y `test_faltante_por_fecha_aunque_el_total_alcance`. |
| "Disponible para gastar" nunca incluye dinero comprometido | `apps/personal/tests/test_availability.py` y `test_loaders.py::test_disponible_real` (pagos pendientes, ahorro pendiente, reserva y cuentas de ahorro descontados). |
| Transferencias internas y retiros de efectivo no cuentan como gasto | `apps/ledger/tests/test_classification.py` y `test_balances.py::test_transferencia_y_retiro_no_son_gasto`. |
| Un comprobante subido dos veces se marca como duplicado sospechoso | `apps/receipts/tests/test_ingest.py::test_mismo_archivo_dos_veces_es_duplicado_sospechoso` (sin volver a llamar a la IA) y duplicado por contenido. |
| Ninguna cifra de la narrativa de IA difiere del motor (test automatizado) | `apps/ai/tests/test_guards.py` y `apps/planning/tests/test_generate.py::test_ninguna_cifra_de_la_narrativa_difiere_del_motor` (viable, ajustado y no viable); cifras inventadas nunca se guardan. |
| Cobertura ≥ 90 % en `services/` de cálculo | `make cov-services`: 99 %. |

Comandos: `make check` (ruff, mypy, pytest con cobertura, `check --deploy`) y `make e2e`.
