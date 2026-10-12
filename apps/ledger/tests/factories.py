import datetime
from decimal import Decimal

import factory

from apps.ledger.choices import AccountType, Direction, TxKind
from apps.ledger.models import Account, Transaction


class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account

    name = factory.Sequence(lambda n: f"Cuenta {n}")
    type = AccountType.BANCO
    currency = factory.LazyAttribute(lambda o: o.workspace.currency)
    opening_balance = Decimal("0")


class TransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Transaction

    workspace = factory.LazyAttribute(lambda o: o.account.workspace)
    date = datetime.date(2026, 10, 5)
    amount = Decimal("100.00")
    direction = Direction.OUT
    kind = TxKind.GASTO
