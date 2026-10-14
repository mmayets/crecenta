"""Valores enumerados del libro de movimientos y su significado contable."""

from django.db import models


class AccountType(models.TextChoices):
    EFECTIVO = "efectivo", "Efectivo"
    BANCO = "banco", "Cuenta bancaria"
    TARJETA = "tarjeta", "Tarjeta de crédito"
    BILLETERA = "billetera", "Billetera digital"


class CategoryGroup(models.TextChoices):
    INGRESO = "ingreso", "Ingresos"
    # Persona
    COMPROMISO_FIJO = "compromiso_fijo", "Compromisos fijos"
    ESENCIAL_VARIABLE = "esencial_variable", "Esenciales variables"
    AHORRO = "ahorro", "Ahorro"
    DISCRECIONAL = "discrecional", "Discrecionales"
    # Negocio
    COSTO_VARIABLE = "costo_variable", "Costos variables"
    GASTO_OPERATIVO = "gasto_operativo", "Gastos operativos"
    FINANCIAMIENTO = "financiamiento", "Financiamiento"
    PROPIETARIO = "propietario", "Propietario"


PERSONAL_GROUPS = {
    CategoryGroup.INGRESO,
    CategoryGroup.COMPROMISO_FIJO,
    CategoryGroup.ESENCIAL_VARIABLE,
    CategoryGroup.AHORRO,
    CategoryGroup.DISCRECIONAL,
}
BUSINESS_GROUPS = {
    CategoryGroup.INGRESO,
    CategoryGroup.COSTO_VARIABLE,
    CategoryGroup.GASTO_OPERATIVO,
    CategoryGroup.FINANCIAMIENTO,
    CategoryGroup.PROPIETARIO,
}


class Rubro(models.TextChoices):
    """Rubro de cada gasto personal (clasificación tipo DGII de los gastos de consumo)."""

    ALIMENTACION = "alimentacion", "Alimentación"
    EDUCACION = "educacion", "Educación, Arte y Cultura"
    SALUD = "salud", "Salud"
    VIVIENDA = "vivienda", "Vivienda"
    VESTIMENTA = "vestimenta", "Vestimenta"
    TURISMO = "turismo_nacional", "Turismo Nacional"
    OTRO = "otro", "Otro"


class Direction(models.TextChoices):
    IN = "in", "Entrada"
    OUT = "out", "Salida"


class TxKind(models.TextChoices):
    INGRESO = "ingreso", "Ingreso"
    GASTO = "gasto", "Gasto"
    TRANSFERENCIA_INTERNA = "transferencia_interna", "Transferencia entre mis cuentas"
    RETIRO_EFECTIVO = "retiro_efectivo", "Retiro de efectivo"
    PRESTAMO = "prestamo", "Préstamo"
    PAGO_DEUDA = "pago_deuda", "Pago de deuda"
    VENTA = "venta", "Venta"
    COMPRA_INVENTARIO = "compra_inventario", "Compra de inventario"
    # Negocio (Fase 2): mueven efectivo pero no son venta ni gasto del resultado.
    COBRO_CXC = "cobro_cxc", "Cobro de cuenta por cobrar"
    PAGO_CXP = "pago_cxp", "Pago a proveedor"
    APORTE_PROPIETARIO = "aporte_propietario", "Aporte del propietario"
    RETIRO_PROPIETARIO = "retiro_propietario", "Retiro del propietario"


class TxStatus(models.TextChoices):
    CONFIRMADO = "confirmado", "Confirmado"
    PENDIENTE_REVISION = "pendiente_revision", "Pendiente de revisión"


class TxSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    VOZ = "voz", "Nota de voz"
    TEXTO = "texto", "Texto libre"
    COMPROBANTE = "comprobante", "Comprobante"
    OFFLINE = "offline", "Sin conexión"
