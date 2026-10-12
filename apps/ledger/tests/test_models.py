from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.ledger.choices import CategoryGroup, Direction, TxKind
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.recording import create_account, ensure_system_categories
from apps.ledger.system_categories import BUSINESS, PERSONAL

from .factories import AccountFactory, TransactionFactory

pytestmark = pytest.mark.django_db


def cat(ws, name):
    return Category.objects.for_workspace(ws).get(name=name)


class TestCategoriasDelSistema:
    def test_espacio_personal(self, personal_ws):
        cats = Category.objects.for_workspace(personal_ws)
        assert cats.count() == len(PERSONAL)
        assert all(c.is_system for c in cats)
        assert cat(personal_ws, "Alimentación").group == CategoryGroup.ESENCIAL_VARIABLE
        (cuenta,) = Account.objects.for_workspace(personal_ws)
        assert (cuenta.name, cuenta.type, cuenta.currency) == ("Efectivo", "efectivo", "DOP")

    def test_espacio_negocio(self, business_ws):
        assert Category.objects.for_workspace(business_ws).count() == len(BUSINESS)
        assert cat(business_ws, "Materia prima").group == CategoryGroup.COSTO_VARIABLE

    def test_idempotente(self, personal_ws):
        assert ensure_system_categories(personal_ws) == 0
        assert Account.objects.for_workspace(personal_ws).count() == 1

    def test_reclasificar(self, personal_ws):
        ropa = cat(personal_ws, "Ropa")
        ropa.group = CategoryGroup.DISCRECIONAL
        ropa.full_clean()
        ropa.save()
        assert cat(personal_ws, "Ropa").group == CategoryGroup.DISCRECIONAL

    def test_grupo_de_negocio_no_aplica_a_persona(self, personal_ws, business_ws):
        c = Category(workspace=personal_ws, name="X", group=CategoryGroup.COSTO_VARIABLE)
        with pytest.raises(ValidationError):
            c.full_clean()
        c = Category(workspace=business_ws, name="Y", group=CategoryGroup.DISCRECIONAL)
        with pytest.raises(ValidationError):
            c.full_clean()
        assert str(cat(personal_ws, "Ropa")) == "Ropa"


class TestCuentas:
    def test_moneda_del_espacio(self, personal_ws):
        cuenta = create_account(personal_ws, "Banco Popular", "banco", "12,500.505")
        assert cuenta.currency == "DOP"
        assert cuenta.opening_balance == Decimal("12500.51")
        assert str(cuenta) == "Banco Popular"

    def test_moneda_distinta_rechazada(self, personal_ws):
        cuenta = Account(workspace=personal_ws, name="US", type="banco", currency="USD")
        with pytest.raises(ValidationError):
            cuenta.full_clean()


class TestMovimiento:
    def test_validaciones(self, personal_ws, other_ws):
        cuenta = AccountFactory(workspace=personal_ws)
        ajena = AccountFactory(workspace=other_ws)
        cases = [
            ({"amount": Decimal("0")}, "amount"),
            ({"direction": Direction.IN}, "direction"),
            ({"account": ajena}, "account"),
            ({"category": cat(other_ws, "Ropa")}, "category"),
            (
                {"category": cat(personal_ws, "Salario")},
                "category",
            ),  # gasto con categoría de ingreso
        ]
        for overrides, field in cases:
            data = {
                "workspace": personal_ws,
                "account": cuenta,
                "date": "2026-10-01",
                "amount": Decimal("10"),
                "direction": Direction.OUT,
                "kind": TxKind.GASTO,
                **overrides,
            }
            with pytest.raises(ValidationError) as exc:
                Transaction(**data).full_clean()
            assert field in exc.value.message_dict, overrides

    def test_ingreso_con_categoria_de_ingreso(self, personal_ws):
        tx = TransactionFactory.build(
            account=AccountFactory(workspace=personal_ws),
            kind=TxKind.INGRESO,
            direction=Direction.IN,
            category=cat(personal_ws, "Salario"),
        )
        tx.full_clean()

    def test_restriccion_monto_positivo_en_bd(self, personal_ws):
        with pytest.raises(IntegrityError):
            TransactionFactory(account=AccountFactory(workspace=personal_ws), amount=Decimal("-1"))

    def test_str(self, personal_ws):
        cuenta = AccountFactory(workspace=personal_ws)
        tx = TransactionFactory(account=cuenta, description="Colmado")
        assert str(tx) == "2026-10-05 -100.00 Colmado"
        tx2 = TransactionFactory(account=cuenta, kind=TxKind.INGRESO, direction=Direction.IN)
        assert str(tx2) == "2026-10-05 +100.00 Ingreso"
