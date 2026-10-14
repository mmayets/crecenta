"""Lectura del código QR de una factura.

Las facturas electrónicas dominicanas (e-CF) llevan un QR con la dirección de consulta de la DGII,
por ejemplo::

    https://ecf.dgii.gov.do/ecf/ConsultaTimbre?RncEmisor=101010101&RncComprador=...
        &ENCF=E310000000123&FechaEmision=10-10-2026&MontoTotal=1180.00&...

De ahí salen el número de la factura (e-NCF), el total, la fecha y el RNC del emisor. Si el QR es
otro texto, se buscan un NCF (B0100000045 o E310000000123) y un total. Nunca se guarda el RNC del
comprador (es un dato de la persona).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlparse

MAX_TEXT = 2000
NCF = re.compile(r"\b([BE]\d{10}|E\d{12})\b", re.IGNORECASE)
TOTAL = re.compile(r"(?:total|monto)\D{0,15}?(\d[\d.,]*)", re.IGNORECASE)


@dataclass(frozen=True)
class InvoiceQR:
    numero: str = ""
    total: Decimal | None = None
    fecha: date | None = None
    rnc_emisor: str = ""
    es_dgii: bool = False

    @property
    def found(self) -> bool:
        return bool(self.numero or self.total)

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["total"] = str(self.total) if self.total is not None else None
        data["fecha"] = self.fecha.isoformat() if self.fecha else None
        return data


def _amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    text = raw.strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", text):
        text = text.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", text):
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value.quantize(Decimal("0.01")) if value > 0 else None


def _date(raw: str | None) -> date | None:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((raw or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse(text: str) -> InvoiceQR:
    text = (text or "").strip()[:MAX_TEXT]
    if not text:
        return InvoiceQR()
    url = urlparse(text)
    if url.scheme in ("http", "https") and url.query:
        params = {k.lower(): v[0] for k, v in parse_qs(url.query).items() if v}
        numero = params.get("encf") or params.get("ncf") or ""
        if numero or "montototal" in params:
            return InvoiceQR(
                numero=numero.upper()[:40],
                total=_amount(params.get("montototal")),
                fecha=_date(params.get("fechaemision")),
                rnc_emisor=re.sub(r"\D", "", params.get("rncemisor", ""))[:11],
                es_dgii=(url.hostname or "").endswith("dgii.gov.do"),
            )
    ncf = NCF.search(text)
    total = TOTAL.search(text)
    return InvoiceQR(
        numero=ncf.group(1).upper() if ncf else "",
        total=_amount(total.group(1)) if total else None,
    )
