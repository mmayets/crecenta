"""Datos de demostración (encargo §15.4):

- Persona: el caso RD$50,000 (cobro el día 1), movimientos del mes en curso, ahorro apartado y un
  plan aceptado.
- Vendedora "vendedor@crecenta.app" (misma contraseña) con rol vendedor en Dulces Ariel (Fase 4).
- Negocio "Dulces Ariel": repostería con tres productos (el bizcocho de costo RD$600 a RD$857.14,
  margen del 30 %), gastos fijos, metas, ventas de contado y a crédito de este mes y del anterior,
  un cobro parcial, una compra a crédito, un retiro hacia la persona y una propuesta de plan del
  negocio (ver `apps/business/services/demo.py`).

Uso: python manage.py seed_demo [--email …] [--password …] [--reset]
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.alerts.services.evaluate import evaluate_workspace
from apps.business.models import Product
from apps.business.services.demo import BIZCOCHO, load_business_case
from apps.ledger.choices import Direction, TxKind
from apps.ledger.models import Account
from apps.ledger.services.recording import (
    TxData,
    create_account,
    record_transaction,
    record_transfer,
)
from apps.onboarding.services.steps import BUSINESS_STEP_KEYS, STEP_KEYS, get_state
from apps.personal.services.demo import category, load_personal_case
from apps.planning.services.generate import (
    narrate_plan,
    request_business_plan,
    request_personal_plan,
)
from apps.planning.services.lifecycle import accept_plan
from apps.workspaces.models import Membership
from apps.workspaces.services.workspaces import create_workspaces_for_usage

DEFAULT_EMAIL = "demo@crecenta.app"
DEFAULT_PASSWORD = "Demo-Crecenta-2026"  # noqa: S105 - cuenta de demostración local
SELLER_EMAIL = "vendedor@crecenta.app"


class Command(BaseCommand):
    help = "Crea una persona y un negocio de demostración."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--email", default=DEFAULT_EMAIL)
        parser.add_argument("--password", default=DEFAULT_PASSWORD)
        parser.add_argument(
            "--reset", action="store_true", help="Borra la demo y la vuelve a crear"
        )

    def handle(self, *args, email: str, password: str, reset: bool, **options) -> None:
        from config.celery import app

        app.conf.task_always_eager = True  # no depende de Redis ni de un worker
        existing = User.objects.filter(email=email).first()
        if existing and not reset:
            self.stdout.write(f"La demo ya existe ({email}). Usa --reset para recrearla.")
            return
        if existing and not existing.owned_workspaces.filter(name="Dulces Ariel").exists():
            raise CommandError(f"{email} no es una cuenta de demostración; no se borrará.")
        if existing:
            existing.owned_workspaces.all().delete()
            existing.delete()

        with transaction.atomic():
            user = User.objects.create_user(email, password, first_name="Ariel")
            personal, business = create_workspaces_for_usage(
                user, "ambos", business_name="Dulces Ariel"
            )
            seller = self._seller(business, password)
            today = timezone.localdate()
            self._personal(user, personal, today)
            load_business_case(business, user, personal, today, seller=seller)
            self._finish_onboarding(business)
        # Fuera de la transacción: la explicación del plan se genera aquí mismo (sin worker).
        plan = request_personal_plan(personal, user, timezone.localdate())
        plan = narrate_plan(plan.pk)
        accept_plan(plan, user)
        evaluate_workspace(personal)
        business_plan = narrate_plan(request_business_plan(business, user, timezone.localdate()).pk)
        evaluate_workspace(business)

        self.stdout.write(self.style.SUCCESS("Demo lista."))
        self.stdout.write(f"  Correo: {email}\n  Contraseña: {password}")
        if seller is not None:
            self.stdout.write(f"  Vendedora de Dulces Ariel: {seller.email} (misma contraseña)")
        self.stdout.write(
            f"  Plan personal: {plan.plan_status} · Plan del negocio: "
            f"{business_plan.plan_status} · Producto: "
            f"{Product.objects.get(workspace=business, name=BIZCOCHO).name}"
        )

    def _seller(self, business, password: str) -> User | None:
        """Vendedora de la demo. Una cuenta con espacios propios no se toca."""
        existing = User.objects.filter(email=SELLER_EMAIL).first()
        if existing is not None:
            if existing.owned_workspaces.exists():
                self.stdout.write(f"  {SELLER_EMAIL} ya tiene espacios propios: sin vendedora.")
                return None
            existing.delete()
        seller = User.objects.create_user(SELLER_EMAIL, password, first_name="Carla")
        Membership.objects.create(user=seller, workspace=business, role=Membership.Role.VENDEDOR)
        return seller

    def _finish_onboarding(self, ws) -> None:
        state = get_state(ws)
        for step in BUSINESS_STEP_KEYS if ws.is_business else STEP_KEYS:
            state.mark(step)
        state.finished_at = timezone.now()
        state.save()

    def _personal(self, user: User, ws, today: date) -> None:
        load_personal_case(ws)
        self._finish_onboarding(ws)

        banco = create_account(ws, "Banco Popular", "banco")
        ahorro = create_account(ws, "Ahorros", "banco", is_savings=True)
        efectivo = Account.objects.for_workspace(ws).get(name="Efectivo")
        start = today.replace(day=1)

        def spend(account, name, amount, day, kind=TxKind.GASTO):
            on = start.replace(day=day)
            if on > today:
                return
            record_transaction(
                ws,
                user,
                TxData(
                    account=account,
                    date=on,
                    amount=Decimal(amount),
                    direction=Direction.IN if kind == TxKind.INGRESO else Direction.OUT,
                    kind=kind,
                    category=category(ws, name),
                    description=name,
                ),
            )

        spend(banco, "Salario", "50000", 1, TxKind.INGRESO)
        record_transfer(
            ws,
            user,
            from_account=banco,
            to_account=efectivo,
            amount="4000",
            on=start,
            kind=TxKind.RETIRO_EFECTIVO,
        )
        spend(banco, "Alquiler o hipoteca", "15000", min(5, today.day))
        spend(efectivo, "Alimentación", "2350", min(3, today.day))
        spend(efectivo, "Transporte y combustible", "900", min(4, today.day))
        spend(banco, "Restaurantes y delivery", "1200", min(6, today.day))
        if today.day >= 2:
            record_transfer(
                ws,
                user,
                from_account=banco,
                to_account=ahorro,
                amount="7000",
                on=start.replace(day=2),
                category=category(ws, "Ahorro"),
            )
