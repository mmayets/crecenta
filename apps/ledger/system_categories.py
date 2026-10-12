"""Categorías que se crean con cada espacio. El usuario puede renombrarlas o reclasificarlas
(p. ej. mover "Ropa" de esencial a discrecional), pero no eliminarlas."""

from .choices import CategoryGroup as G

PERSONAL = [
    ("Salario", G.INGRESO),
    ("Otros ingresos", G.INGRESO),
    ("Alquiler o hipoteca", G.COMPROMISO_FIJO),
    ("Electricidad", G.COMPROMISO_FIJO),
    ("Agua", G.COMPROMISO_FIJO),
    ("Internet y teléfono", G.COMPROMISO_FIJO),
    ("Seguros", G.COMPROMISO_FIJO),
    ("Educación", G.COMPROMISO_FIJO),
    ("Préstamos y deudas", G.COMPROMISO_FIJO),
    ("Alimentación", G.ESENCIAL_VARIABLE),
    ("Transporte y combustible", G.ESENCIAL_VARIABLE),
    ("Aseo y hogar", G.ESENCIAL_VARIABLE),
    ("Salud y farmacia", G.ESENCIAL_VARIABLE),
    ("Ropa", G.ESENCIAL_VARIABLE),
    ("Ahorro", G.AHORRO),
    ("Ocio y salidas", G.DISCRECIONAL),
    ("Restaurantes y delivery", G.DISCRECIONAL),
    ("Suscripciones", G.DISCRECIONAL),
    ("Regalos", G.DISCRECIONAL),
    ("Otros gastos", G.DISCRECIONAL),
]

BUSINESS = [
    ("Ventas", G.INGRESO),
    ("Otros ingresos del negocio", G.INGRESO),
    ("Materia prima", G.COSTO_VARIABLE),
    ("Empaque", G.COSTO_VARIABLE),
    ("Comisiones", G.COSTO_VARIABLE),
    ("Entrega", G.COSTO_VARIABLE),
    ("Alquiler del local", G.GASTO_OPERATIVO),
    ("Servicios (luz, agua, internet)", G.GASTO_OPERATIVO),
    ("Nómina", G.GASTO_OPERATIVO),
    ("Publicidad", G.GASTO_OPERATIVO),
    ("Otros gastos operativos", G.GASTO_OPERATIVO),
    ("Préstamos del negocio", G.FINANCIAMIENTO),
    ("Aportes del propietario", G.PROPIETARIO),
    ("Retiros del propietario", G.PROPIETARIO),
]

DEFAULT_ACCOUNT_NAME = "Efectivo"
