import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.workspaces.models import WorkspaceTransfer


def test_transferencia_entre_espacios_distintos(personal_ws, business_ws):
    t = WorkspaceTransfer.objects.create(
        from_workspace=business_ws,
        to_workspace=personal_ws,
        kind=WorkspaceTransfer.Kind.RETIRO_PROPIETARIO,
        amount=Decimal("5000"),
        date=datetime.date(2026, 10, 13),
    )
    assert "Retiro del propietario" in str(t)
    with pytest.raises(IntegrityError):
        WorkspaceTransfer.objects.create(
            from_workspace=business_ws,
            to_workspace=business_ws,
            kind=WorkspaceTransfer.Kind.APORTE,
            amount=Decimal("1"),
            date=datetime.date(2026, 10, 13),
        )
