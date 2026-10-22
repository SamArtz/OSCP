"""Precisión y umbrales únicos para valores, indicadores y alertas del backend."""

from decimal import Decimal, ROUND_HALF_UP

EXCESS_DAYS = 90
RISK_DAYS = 14
PRECISION = 6
STEP = Decimal("0.000001")
HEALTH_STATES = ("quiebre", "exceso", "optimo", "sin_datos")


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


def calcular_estado_sku(
    stock_utilizable: int | None,
    demanda_diaria: float | None,
    demanda_no_cubierta_14_dias: float | None,
) -> dict:
    """Única clasificación de salud para dashboard, mesa OCS y clientes.

    El faltante proviene de FEFO a 14 días incluyendo las ETA. La urgencia
    durante el lead time es un dato separado, no otra definición de salud.
    """
    coverage = coverage_metrics(stock_utilizable, demanda_diaria)
    uncovered = shortfall(demanda_no_cubierta_14_dias) if demanda_no_cubierta_14_dias is not None else None
    risk = None
    if stock_utilizable == 0:
        risk = True
    elif stock_utilizable is not None and uncovered is not None:
        risk = uncovered > 0
    if stock_utilizable is None:
        state = "sin_datos"
    elif risk:
        state = "quiebre"
    elif demanda_diaria is None or uncovered is None:
        state = "sin_datos"
    elif coverage["overstock"]:
        state = "exceso"
    else:
        state = "optimo"
    return {
        "estado_salud": state,
        "cobertura_dias": coverage["days"], "sobreinventario": coverage["overstock"],
        "unidades_excedentes_90_dias": coverage["excess"],
        "demanda_no_cubierta_14_dias": uncovered, "riesgo_quiebre_14_dias": risk,
    }


def count_sku_states(rows: list[dict]) -> dict[str, int]:
    """Cuenta una vez cada fila consolidada usando su estado ya calculado."""
    return {state: sum(row["estado_salud"] == state for row in rows) for state in HEALTH_STATES}
