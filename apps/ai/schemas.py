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


# ---------------------------------------------------------------- onboarding de negocio


class ProductoExtraido(_Base):
    nombre: str = Field(max_length=120)
    precio: Decimal = Field(ge=0)
    costo: Decimal | None = Field(default=None, ge=0)
    unidades_mes: Decimal | None = Field(default=None, ge=0)
    es_servicio: bool = False
    minutos: int | None = Field(default=None, gt=0, le=1440)


class GastoNegocioExtraido(_Base):
    nombre: str = Field(max_length=80)
    monto: Decimal = Field(gt=0)
    frecuencia: Literal["mensual", "quincenal", "semanal"] = "mensual"
    dia: int | None = Field(default=None, ge=1, le=31)


class BusinessOnboardingExtraction(_Base):
    actividad: str | None = Field(default=None, max_length=120)
    modelo: Literal["productos", "servicios", "mixto"] | None = None
    cobra_itbis: bool | None = None
    productos: list[ProductoExtraido] = Field(default_factory=list, max_length=20)
    gastos: list[GastoNegocioExtraido] = Field(default_factory=list, max_length=20)
    efectivo: Decimal | None = Field(default=None, ge=0)
    margen_objetivo_pct: Decimal | None = Field(default=None, ge=0, le=95)
    ganancia_objetivo: Decimal | None = Field(default=None, ge=0)
    retiro_mensual: Decimal | None = Field(default=None, ge=0)
    # Rutas de los campos dudosos, p. ej. "productos.0.costo".
    campos_dudosos: list[str] = Field(default_factory=list, max_length=40)


# ---------------------------------------------------------------- asistente de espacios


class AssistantTurn(_Base):
    """Un turno del asistente que guía la creación de espacios: lo que dice y lo que entendió.

    Solo propone: el servidor valida el borrador, decide la etapa y crea los espacios cuando la
    persona confirma.
    """

    mensaje: str = Field(default="", max_length=600)
    uso: Literal["persona", "negocio", "ambos"] | None = None
    nombre_negocio: str | None = Field(default=None, max_length=80)
    moneda: Literal["DOP", "USD"] | None = None
    moneda_negocio: Literal["DOP", "USD"] | None = None


class MovementTurn(_Base):
    """Un turno de Sophia al registrar un movimiento: lo que dice y lo que entendió del mensaje.

    Solo propone: el servidor empareja cuenta y categoría con las reales, decide qué falta y
    guarda únicamente cuando la persona confirma.
    """

    mensaje: str = Field(default="", max_length=400)
    tipo: (
        Literal[
            "gasto",
            "ingreso",
            "pago_deuda",
            "compra_inventario",
            "transferencia_interna",
            "retiro_efectivo",
        ]
        | None
    ) = None
    monto: Decimal | None = Field(default=None, gt=0)
    fecha: date | None = None
    categoria: str | None = Field(default=None, max_length=60)
    cuenta: str | None = Field(default=None, max_length=60)
    descripcion: str | None = Field(default=None, max_length=140)


class HelpAnswer(_Base):
    """Respuesta del asistente a «¿cómo hago…?»: texto breve y destinos de un catálogo cerrado."""

    mensaje: str = Field(min_length=1, max_length=500)
    destinos: list[str] = Field(default_factory=list, max_length=3)


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
    # NCF (B0100000045), e-NCF (E310000000123) o el número de factura impreso.
    numero_factura: str | None = Field(default=None, max_length=40)
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


# ---------------------------------------------------------------- revisión del ahorro


class RevisionAhorro(_Base):
    """Sophia explica si el ahorro alcanza y cuál opción conviene. Las cifras las calcula la app."""

    mensaje: str = Field(max_length=900)
    motivos: list[str] = Field(default_factory=list, max_length=5)
    metodo_recomendado: str = Field(max_length=20)
    # «Saber más»: el 50/30/20 explicado con un ejemplo hecho con el ingreso de la persona.
    explicacion_metodo: str = Field(default="", max_length=1500)


SCHEMAS: dict[str, type[BaseModel]] = {
    s.__name__: s for s in (PlanNarrative, OnboardingExtraction, ReceiptExtraction, QuickEntry)
}
