"""Esquemas estrictos de lo que la IA puede devolver. Toda respuesta se valida contra uno de ellos.

Los montos se reciben como Decimal (nunca float en el sistema); el motor y los validadores los
contrastan contra las cifras calculadas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------------------------------------------------------------- plan (encargo §9)


class AccionSugerida(_Base):
    tipo: str = Field(max_length=60)
    parametros: dict[str, Any] = Field(default_factory=dict)


class Recomendacion(_Base):
    titulo: str = Field(max_length=120)
    detalle: str = Field(max_length=800)
    impacto_rd: Decimal = Decimal("0")
    datos_usados: list[str] = Field(default_factory=list, max_length=12)
    es_proyeccion: bool = False
    accion_sugerida: AccionSugerida | None = None


class CambioIA(_Base):
    categoria: str = Field(max_length=80)
    de: Decimal
    a: Decimal


class AlternativaIA(_Base):
    codigo: str | None = Field(default=None, max_length=40)  # código de la alternativa del motor
    nombre: str = Field(max_length=120)
    cambios: list[CambioIA] = Field(default_factory=list, max_length=12)
    explicacion: str = Field(max_length=800)


class PlanNarrative(_Base):
    resumen: str = Field(max_length=1200)
    estado: Literal["viable", "ajustado", "no_viable"]
    recomendaciones: list[Recomendacion] = Field(default_factory=list, max_length=8)
    alternativas: list[AlternativaIA] = Field(default_factory=list, max_length=8)
    advertencias_datos_faltantes: list[str] = Field(default_factory=list, max_length=10)
    preguntas_para_mejorar_el_plan: list[str] = Field(default_factory=list, max_length=6)


# ---------------------------------------------------------------- onboarding conversacional


Frecuencia = Literal["mensual", "quincenal", "semanal", "variable"]


class IngresoExtraido(_Base):
    nombre: str = Field(default="Ingreso", max_length=60)
    monto: Decimal = Field(gt=0, description="Monto neto de cada cobro")
    frecuencia: Frecuencia = "mensual"
    dias_cobro: list[int] = Field(default_factory=list, max_length=2)


class CuentaExtraida(_Base):
    nombre: str = Field(max_length=60)
    tipo: Literal["efectivo", "banco", "tarjeta", "billetera"] = "banco"
    saldo: Decimal = Decimal("0")


class CompromisoExtraido(_Base):
    nombre: str = Field(max_length=60)
    monto: Decimal = Field(gt=0)
    frecuencia: Literal["mensual", "quincenal", "semanal"] = "mensual"
    dia_vencimiento: int | None = Field(default=None, ge=0, le=31)
    categoria: str | None = Field(default=None, max_length=60)


class EsencialExtraido(_Base):
    categoria: str = Field(max_length=60)
    monto: Decimal = Field(ge=0)


class DeudaExtraida(_Base):
    nombre: str = Field(max_length=60)
    cuota: Decimal = Field(gt=0)
    saldo: Decimal | None = Field(default=None, ge=0)
    dia_pago: int | None = Field(default=None, ge=1, le=31)
    tasa_anual: Decimal | None = None


class MetaExtraida(_Base):
    proposito: str = Field(max_length=80)
    meta: Decimal | None = Field(default=None, gt=0)
    aporte: Decimal = Field(gt=0)
    frecuencia: Literal["diaria", "semanal", "quincenal", "mensual"] = "mensual"
    plazo: date | None = None


class OnboardingExtraction(_Base):
    ingresos: list[IngresoExtraido] = Field(default_factory=list, max_length=6)
    cuentas: list[CuentaExtraida] = Field(default_factory=list, max_length=10)
    compromisos: list[CompromisoExtraido] = Field(default_factory=list, max_length=20)
    esenciales: list[EsencialExtraido] = Field(default_factory=list, max_length=12)
    deudas: list[DeudaExtraida] = Field(default_factory=list, max_length=10)
    metas_ahorro: list[MetaExtraida] = Field(default_factory=list, max_length=5)
    ocio_deseado: Decimal | None = Field(default=None, ge=0)
    # Rutas de los campos dudosos, p. ej. "compromisos.0.dia_vencimiento".
    campos_dudosos: list[str] = Field(default_factory=list, max_length=40)


# ---------------------------------------------------------------- comprobantes (OCR)


class LineaComprobante(_Base):
    descripcion: str = Field(max_length=120)
    cantidad: Decimal | None = None
    precio: Decimal | None = None


class ReceiptExtraction(_Base):
    comercio: str | None = Field(default=None, max_length=120)
    fecha: date | None = None
    total: Decimal | None = Field(default=None, ge=0)
    moneda: Literal["DOP", "USD"] | None = None
    categoria_propuesta: str | None = Field(default=None, max_length=60)
    medio_pago: Literal["efectivo", "tarjeta", "transferencia", "otro"] | None = None
    lineas: list[LineaComprobante] = Field(default_factory=list, max_length=60)
    # Confianza por campo entre 0 y 1 (comercio, fecha, total, categoria_propuesta, medio_pago).
    confianza: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------- registro por texto o voz


class QuickEntry(_Base):
    tipo: Literal["gasto", "ingreso", "transferencia_interna", "retiro_efectivo", "pago_deuda"]
    monto: Decimal = Field(gt=0)
    fecha: date | None = None
    categoria: str | None = Field(default=None, max_length=60)
    descripcion: str = Field(default="", max_length=140)
    cuenta: str | None = Field(default=None, max_length=60)
    confianza: dict[str, float] = Field(default_factory=dict)


SCHEMAS: dict[str, type[BaseModel]] = {
    s.__name__: s for s in (PlanNarrative, OnboardingExtraction, ReceiptExtraction, QuickEntry)
}
