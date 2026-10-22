"""Precisión y umbrales únicos para valores, indicadores y alertas del backend."""

from decimal import Decimal, ROUND_HALF_UP

EXCESS_DAYS = 90
RISK_DAYS = 14
PRECISION = 6
STEP = Decimal("0.000001")


def quantity(value: float | int | Decimal) -> float:
    """La misma precisión que se publica en JSON; absorbe residuos de float."""
    return float(Decimal(str(value)).quantize(STEP, rounding=ROUND_HALF_UP))


def shortfall(required: float | Decimal, available: float | Decimal = 0) -> float:
    """Solo hay faltante/alerta si es positivo en la precisión publicada."""
    return max(0.0, quantity(Decimal(str(required)) - Decimal(str(available))))


def coverage_metrics(available: int | None, daily_mean: float | None) -> dict:
    """90 exactos no es exceso. Stock sin rotación conocida sí es excedente.

    La cobertura, la bandera y el capital usan una única decisión a seis
    decimales. None no equivale a cero ni a cobertura infinita.
    """
    if available is None or daily_mean is None:
        return dict(days=None, excess=None, overstock=None)
    if daily_mean == 0:
        return dict(days=None, excess=float(available), overstock=available > 0)
    days = quantity(Decimal(available) / Decimal(str(daily_mean)))
    overstock = days > EXCESS_DAYS
    excess = shortfall(available, Decimal(EXCESS_DAYS) * Decimal(str(daily_mean))) if overstock else 0.0
    return dict(days=days, excess=excess, overstock=overstock)
