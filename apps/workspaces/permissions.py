"""Permisos por rol en un espacio (docs/fase4.md §2).

Cada vista declara el permiso que necesita (`workspace_required(perm=…)`); si no declara ninguno se
exige `finanzas`, así una vista nueva queda cerrada para el vendedor hasta que alguien decida
abrirla. El espacio personal solo tiene a su propietario.
"""

from __future__ import annotations

VENDER = "vender"  # registrar ventas y cobros, ver precios y existencias
FINANZAS = "finanzas"  # costos, ganancias, reportes, plan, movimientos, compras y gastos
PROPIETARIO = "propietario"  # retiros/aportes, equipo

ROLE_PERMS: dict[str, frozenset[str]] = {
    "owner": frozenset({VENDER, FINANZAS, PROPIETARIO}),
    "admin": frozenset({VENDER, FINANZAS}),
    "vendedor": frozenset({VENDER}),
}


def perms_for(role: str | None) -> frozenset[str]:
    return ROLE_PERMS.get(role or "", frozenset())


def can(role: str | None, perm: str) -> bool:
    return perm in perms_for(role)
