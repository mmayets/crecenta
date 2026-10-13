"""Crea (o recrea) las personas de las pruebas de punta a punta y devuelve sus datos en JSON.

- Una persona con su espacio personal (gastos sin conexión).
- Un negocio de esa persona con un producto y una vendedora (ventas sin conexión).
"""

import json
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.business.models import Product
from apps.workspaces.models import Membership
from apps.workspaces.services.workspaces import create_workspace, create_workspaces_for_usage

EMAIL = "e2e@crecenta.test"
SELLER_EMAIL = "e2e-vendedor@crecenta.test"
PASSWORD = "Prueba-E2E-2026"  # noqa: S105 - usuario desechable de pruebas locales


class Command(BaseCommand):
    help = "Prepara los usuarios de las pruebas E2E (solo para entornos de desarrollo)."

    def handle(self, *args, **options) -> None:
        User.objects.filter(email__in=[EMAIL, SELLER_EMAIL]).delete()
        user = User.objects.create_user(EMAIL, PASSWORD, first_name="Prueba")
        (workspace,) = create_workspaces_for_usage(user, "persona")
        business = create_workspace(user, "business", name="Colmado E2E")
        Product.objects.create(
            workspace=business, name="Refresco", price=Decimal("75"), unit_cost=Decimal("50")
        )
        seller = User.objects.create_user(SELLER_EMAIL, PASSWORD, first_name="Vendedora")
        Membership.objects.create(user=seller, workspace=business, role=Membership.Role.VENDEDOR)
        self.stdout.write(
            json.dumps(
                {
                    "email": EMAIL,
                    "password": PASSWORD,
                    "ws": str(workspace.pk),
                    "seller": SELLER_EMAIL,
                    "business": str(business.pk),
                }
            )
        )
