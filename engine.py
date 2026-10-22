"""Motor OCS determinista sobre DataFrames validados por el ETL.

No modifica los argumentos, no lee Excel y no ejecuta compras. Solo necesita
Pandas y la biblioteca estándar. Las unidades son físicas; los precios, USD/unidad.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import ceil, isfinite, sqrt
from statistics import NormalDist

import pandas as pd


class EngineInputError(ValueError):
    """Dato que el ETL admite, pero necesita aclaración antes de una OCS."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReplenishmentConfig:
    window_days: int = 60
    service_level: float = 0.95
    seasonal_weight: float = 0.5
    review_days: int = 0

    def __post_init__(self):
        if isinstance(self.window_days, bool) or not isinstance(self.window_days, int) or not 30 <= self.window_days <= 60:
            raise ValueError("window_days debe ser un entero entre 30 y 60.")
        if not isfinite(self.service_level) or not 0.5 < self.service_level < 1:
            raise ValueError("service_level debe estar entre 0.5 y 1, sin incluir extremos.")
        if not isfinite(self.seasonal_weight) or not 0 <= self.seasonal_weight <= 1:
            raise ValueError("seasonal_weight debe estar entre 0 y 1.")
        if isinstance(self.review_days, bool) or not isinstance(self.review_days, int) or not 0 <= self.review_days <= 30:
            raise ValueError("review_days debe ser un entero entre 0 y 30.")


def warn(items: list, sku: str | None, code: str, message: str):
    items.append({"sku_id": sku, "codigo": code, "mensaje": message})


@dataclass(frozen=True)
class DemandProfile:
    daily: pd.Series
    mean: float
    sigma: float
    weekday_factors: tuple[float, ...]
    seasonal: bool

    def forecast(self, cutoff: pd.Timestamp, days: int) -> list[float]:
        return [
            self.mean * self.weekday_factors[day.dayofweek]
            for day in pd.date_range(cutoff, periods=days, freq="D")
        ]

    def total(self, start: pd.Timestamp, days: int) -> float:
        """Suma semanas completas sin expandir una vida útil potencialmente larga."""
        weeks, remainder = divmod(days, 7)
        factors = weeks * sum(self.weekday_factors)
        factors += sum(self.weekday_factors[(start.dayofweek + offset) % 7] for offset in range(remainder))
        return self.mean * factors


def demand_profile(
    history: pd.Series, cutoff: pd.Timestamp, config: ReplenishmentConfig
) -> DemandProfile | None:
    """Promedio ponderado y estacionalidad semanal, sin usar el día del corte.

    history contiene salidas facturadas + bonos por día. Una NC es una devolución
    de una venta pasada, no demanda negativa del día de su emisión.
    """
    history = history.loc[history.index < cutoff].sort_index()
    if history.empty:
        return None
    # No se inventan ceros anteriores a la primera venta observada de un SKU nuevo.
    start = max(cutoff - pd.Timedelta(days=config.window_days), history.index.min())
    days = pd.date_range(start, cutoff - pd.Timedelta(days=1), freq="D")
    daily = history.reindex(days, fill_value=0).astype(float)
    weights = pd.Series(range(1, len(daily) + 1), index=days, dtype=float)
    total_weight = float(weights.sum())
    mean = float((daily * weights).sum() / total_weight)
    groups = daily.groupby(daily.index.dayofweek)
    seasonal = (
        len(daily) >= 28 and len(groups) == 7
        and bool(groups.size().ge(4).all()) and mean > 0
        and config.seasonal_weight > 0
    )
    factors = [1.0] * 7
    if seasonal:
        weekday_means = (daily * weights).groupby(days.dayofweek).sum() / weights.groupby(days.dayofweek).sum()
        level = float(weekday_means.mean())
        factors = [
            (1 - config.seasonal_weight) + config.seasonal_weight * float(weekday_means.loc[day]) / level
            for day in range(7)
        ]
    fitted = pd.Series([mean * factors[day.dayofweek] for day in days], index=days)
    residual = daily - fitted
    residual_mean = float((residual * weights).sum() / total_weight)
    # Varianza muestral ponderada; la estacionalidad explicada no infla el colchón.
    denominator = total_weight - float(weights.pow(2).sum()) / total_weight
    variance = float(((residual - residual_mean).pow(2) * weights).sum() / denominator) if denominator > 0 else 0.0
    return DemandProfile(daily, mean, sqrt(max(0.0, variance)), tuple(factors), seasonal)


def simulate_fefo(lots: pd.DataFrame, cutoff: pd.Timestamp, forecast: list[float]) -> dict:
    """Consume primero los lotes que vencen antes, por día y con ETA al inicio.

    El vencimiento es inclusivo: un lote con fecha de hoy sirve durante hoy.
    El tránsito no trae vencimiento propio en el esquema: se asume vigente en el
    horizonte, se identifica aparte y nunca hereda la caducidad del lote actual.
    """
    horizon = len(forecast)
    deadline = cutoff + pd.Timedelta(days=horizon)
    queue, details, arrivals = [], [], {}
    raw_stock = int(lots.stock_disponible.sum())
    expired_stock = 0
    for lot in lots.itertuples(index=False):
        expiry = lot.fecha_vencimiento_lote.normalize()
        quantity = float(lot.stock_disponible)
        expired = expiry < cutoff
        detail = {
            "bodega_id": str(lot.bodega_id), "lote": str(lot.lote),
            "fecha_vencimiento": expiry.date().isoformat(),
            "stock_disponible": int(quantity), "vencido_al_corte": expired,
            "consumo_estimado_unidades": 0.0, "merma_proyectada_unidades": 0.0,
        }
        details.append(detail)
        if expired:
            expired_stock += int(quantity)
        elif quantity > 0:
            queue.append({"expiry": expiry, "remaining": quantity, "detail": detail})
        if lot.stock_en_transito > 0:
            eta = lot.fecha_llegada_transito.normalize()
            if cutoff <= eta <= deadline:
                arrivals.setdefault(eta, []).append(float(lot.stock_en_transito))
    details.sort(key=lambda item: (item["fecha_vencimiento"], item["bodega_id"], item["lote"]))
    queue.sort(key=lambda item: (item["expiry"], item["detail"]["bodega_id"], item["detail"]["lote"]))
    losses = 0.0
    uncovered = 0.0
    losses_by_day, uncovered_by_day = [], []
    for offset in range(horizon + 1):
        day = cutoff + pd.Timedelta(days=offset)
        for lot in queue:
            if lot["expiry"] is not None and lot["expiry"] < day:
                wasted = lot["remaining"]
                losses += wasted
                lot["detail"]["merma_proyectada_unidades"] += wasted
                lot["remaining"] = 0.0
        # Los lotes de tránsito, sin fecha de vencimiento disponible, van al final.
        for quantity in arrivals.get(day, []):
            queue.append({"expiry": None, "remaining": quantity, "detail": None})
        if offset < horizon:
            required = forecast[offset]
            for lot in queue:
                consumed = min(required, lot["remaining"])
                lot["remaining"] -= consumed
                required -= consumed
                if lot["detail"] is not None:
                    lot["detail"]["consumo_estimado_unidades"] += consumed
                if required <= 0:
                    break
            uncovered += max(0.0, required)
        losses_by_day.append(losses)
        uncovered_by_day.append(uncovered)
    for detail in details:
        for key in ["consumo_estimado_unidades", "merma_proyectada_unidades"]:
            detail[key] = round(detail[key], 6)
    return {
        "raw_stock": raw_stock, "usable_stock": raw_stock - expired_stock,
        "expired_stock": expired_stock, "losses": losses,
        "losses_by_day": losses_by_day, "uncovered_by_day": uncovered_by_day,
        "physical_remaining": sum(lot["remaining"] for lot in queue), "lots": details,
    }


def money(quantity: int, unit_cost: float) -> float:
    return float((Decimal(quantity) * Decimal(str(unit_cost))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def generate_suggested_order(
    sales: pd.DataFrame,
    catalog: pd.DataFrame,
    inventory: pd.DataFrame,
    config: ReplenishmentConfig | None = None,
) -> dict:
    """Consolida por proveedor/SKU; requiere DataFrames tipados del Paso 1.

    ROP = pronóstico(L) + Z * sigma_diaria * sqrt(L).
    Objetivo = pronóstico(L+R) + Z * sigma_diaria * sqrt(L+R).
    Compra = max(0, objetivo - disponible_utilizable - tránsito_a_tiempo + merma_FEFO).
    Con R=0 (predeterminado), objetivo y ROP coinciden. Se redondea solo al final.
    """
    config = config or ReplenishmentConfig()
    warnings, rows = [], []
    cutoff = inventory.fecha_corte.iloc[0].normalize()
    if inventory.fecha_corte.nunique() != 1:
        raise EngineInputError("CORTES_MEZCLADOS", "Se requiere un único corte de inventario.")
    if (catalog.lead_time_dias + config.review_days).gt(730).any():
        raise EngineInputError("HORIZONTE_NO_SOPORTADO", "Lead time más revisión no puede exceder 730 días.")
    transit_rows = inventory.loc[inventory.stock_en_transito.gt(0)]
    if transit_rows.duplicated(["sku_id", "oc_transito_id"], keep=False).any():
        raise EngineInputError(
            "TRANSITO_OC_AMBIGUO",
            "Una OC/SKU aparece con tránsito en varios lotes o bodegas; consolide la cantidad o aporte líneas de OC inequívocas.",
        )
    if inventory.bodega_id.nunique() > 1:
        warn(warnings, None, "STOCK_CONSOLIDADO", "Se consolidan bodegas asumiendo transferencias posibles; ventas no contiene bodega_id.")
    excluded = sales.fecha_factura.dt.normalize().ge(cutoff)
    if excluded.any():
        warn(warnings, None, "VENTAS_DESDE_CORTE_EXCLUIDAS", f"Se excluyen {int(excluded.sum())} filas del día del corte o posteriores para no usar información futura.")
    invoices = sales.loc[sales.tipo_doc.eq("FACTURA") & ~excluded].copy()
    invoices["day"] = invoices.fecha_factura.dt.normalize()
    invoices["demand"] = invoices.unidades_vendidas + invoices.unidades_bonificadas
    grouped = invoices.groupby(["sku_id", "day"]).demand.sum()
    z_score = NormalDist().inv_cdf(config.service_level)
    for item in catalog.sort_values(["proveedor_id", "sku_id"]).itertuples(index=False):
        sku = str(item.sku_id)
        lead = int(item.lead_time_dias)
        horizon = lead + config.review_days
        lots = inventory.loc[inventory.sku_id.eq(sku)]
        history = grouped.loc[sku] if sku in grouped.index.get_level_values(0) else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        profile = demand_profile(history, cutoff, config)
        forecast = profile.forecast(cutoff, horizon) if profile else [0.0] * horizon
        fefo = simulate_fefo(lots, cutoff, forecast)
        demand_lead = sum(forecast[:lead])
        demand_horizon = sum(forecast)
        safety_lead = z_score * profile.sigma * sqrt(lead) if profile else 0.0
        safety_horizon = z_score * profile.sigma * sqrt(horizon) if profile else 0.0
        rop, target = demand_lead + safety_lead, demand_horizon + safety_horizon
        eta = lots.fecha_llegada_transito.dt.normalize()
        has_transit = lots.stock_en_transito.gt(0)
        transit_lead = int(lots.loc[has_transit & eta.between(cutoff, cutoff + pd.Timedelta(days=lead)), "stock_en_transito"].sum())
        transit_eligible = int(lots.loc[has_transit & eta.between(cutoff, cutoff + pd.Timedelta(days=horizon)), "stock_en_transito"].sum())
        transit_total = int(lots.stock_en_transito.sum())
        transit_overdue = int(lots.loc[has_transit & eta.lt(cutoff), "stock_en_transito"].sum())
        transit_late = transit_total - transit_eligible - transit_overdue
        losses_lead = fefo["losses_by_day"][lead]
        position_lead = fefo["usable_stock"] + transit_lead - losses_lead
        position = fefo["usable_stock"] + transit_eligible - fefo["losses"]
        deficit = max(0.0, target - position)
        status = "CALCULADO"
        if item.estado == "DESCONTINUADO":
            status = "DESCONTINUADO"
        elif lots.empty:
            status = "INVENTARIO_DESCONOCIDO"
        elif profile is None:
            status = "SIN_HISTORIAL"
        boxes = max(int(item.moq_cajas), ceil(round(deficit / int(item.unidades_por_caja), 12))) if deficit > 1e-9 and status == "CALCULADO" else 0
        units = boxes * int(item.unidades_por_caja)
        if status != "CALCULADO":
            warn(warnings, sku, status, "No se genera compra automática para este SKU; revise estado, inventario o historial.")
        if profile is not None and len(profile.daily) < 28:
            warn(warnings, sku, "HISTORIAL_CORTO", "Menos de 28 días observados: se usa solo promedio ponderado; la variabilidad es poco confiable.")
        if profile is not None and profile.mean == 0:
            warn(warnings, sku, "DEMANDA_RECIENTE_CERO", "No hay salidas facturadas en la ventana; revise inactividad o posibles rupturas históricas antes de interpretar demanda cero.")
        if fefo["expired_stock"] > 0:
            warn(warnings, sku, "STOCK_VENCIDO_EXCLUIDO", "Se excluyen unidades vencidas del stock utilizable.")
        if fefo["losses"] > 1e-9:
            warn(warnings, sku, "RIESGO_VENCIMIENTO_FEFO", "Parte del stock vigente vencería antes de consumirse; se descuenta de la cobertura.")
        if transit_overdue > 0:
            warn(warnings, sku, "TRANSITO_ATRASADO_EXCLUIDO", "El tránsito con ETA anterior al corte requiere fecha confirmada y no reduce la compra.")
        if transit_late > 0:
            warn(warnings, sku, "TRANSITO_FUERA_HORIZONTE", "El tránsito posterior al horizonte de cobertura no reduce la compra sugerida.")
        if transit_eligible > 0:
            warn(warnings, sku, "VENCIMIENTO_TRANSITO_DESCONOCIDO", "Se supone tránsito vigente al recibirlo; el esquema no informa su vencimiento.")
        # El acumulado a L-1 es la demanda no cubierta antes de recibir la nueva OC.
        uncovered_lead = fefo["uncovered_by_day"][lead - 1] if lead > 0 else 0.0
        if uncovered_lead > 1e-9:
            warn(warnings, sku, "RIESGO_QUIEBRE_ANTES_RECEPCION", "La compra normal no evita el faltante previo a su llegada: revise urgencia o transferencia.")
        if lead == 0 and config.review_days == 0:
            warn(warnings, sku, "HORIZONTE_CERO", "Con plazo y revisión cero el objetivo es cero; configure un horizonte para planificar cobertura.")
        if units > 0 and profile and units > profile.total(cutoff + pd.Timedelta(days=lead), int(item.vida_util_dias)):
            warn(warnings, sku, "MOQ_RIESGO_SOBRESTOCK", "La compra excede la demanda estimada en la vida útil nominal; confirme el vencimiento real del lote entrante.")
        rows.append({
            "proveedor_id": str(item.proveedor_id), "sku_id": sku,
            "nombre_producto": str(item.nombre_producto), "estado_sku": str(item.estado),
            "estado_sugerencia": status,
            "stock_disponible": fefo["raw_stock"] if not lots.empty else None,
            "stock_utilizable": fefo["usable_stock"] if not lots.empty else None,
            "stock_vencido_excluido": fefo["expired_stock"],
            "posible_demanda_censurada": fefo["usable_stock"] == 0 if not lots.empty else None,
            "stock_en_transito": transit_total if not lots.empty else None,
            "stock_en_transito_durante_lead_time": transit_lead,
            "stock_en_transito_a_tiempo": transit_eligible,
            "stock_en_transito_atrasado": transit_overdue,
            "stock_en_transito_fuera_horizonte": transit_late,
            "lead_time_dias": lead,
            "demanda_diaria_ponderada": round(profile.mean, 6) if profile else None,
            "desviacion_diaria_residual": round(profile.sigma, 6) if profile else None,
            "dias_historial_utilizados": len(profile.daily) if profile else 0,
            "modelo": "ponderado_estacional_semanal" if profile and profile.seasonal else "ponderado" if profile else "sin_historial",
            "pronostico_demanda_lead_time": round(demand_lead, 6) if profile else None,
            "stock_seguridad": round(safety_lead, 6) if profile else None,
            "punto_reorden": round(rop, 6) if profile else None,
            "bajo_punto_reorden": position_lead < rop if profile and not lots.empty else None,
            "posicion_inventario_lead_time": round(position_lead, 6) if not lots.empty else None,
            "objetivo_cobertura_unidades": round(target, 6) if profile else None,
            "posicion_inventario_horizonte": round(position, 6) if not lots.empty else None,
            "merma_proyectada_fefo": round(fefo["losses"], 6),
            "stock_fisico_proyectado_horizonte": round(fefo["physical_remaining"], 6) if not lots.empty else None,
            "demanda_no_cubierta_antes_recepcion": round(uncovered_lead, 6) if profile else None,
            "unidades_por_caja": int(item.unidades_por_caja), "moq_cajas": int(item.moq_cajas),
            "cantidad_sugerida_cajas": boxes, "cantidad_sugerida_unidades": units,
            "costo_total_usd": money(units, item.costo_unitario_usd), "prioridad_fefo": fefo["lots"],
        })
    suppliers = []
    for supplier in sorted({row["proveedor_id"] for row in rows}):
        selected = [row for row in rows if row["proveedor_id"] == supplier]
        suppliers.append({
            "proveedor_id": supplier,
            "sku_con_compra": sum(row["cantidad_sugerida_cajas"] > 0 for row in selected),
            "cantidad_total_cajas": sum(row["cantidad_sugerida_cajas"] for row in selected),
            "costo_total_usd": float(sum((Decimal(str(row["costo_total_usd"])) for row in selected), Decimal(0))),
        })
    return {
        "fecha_corte": cutoff.date().isoformat(),
        "parametros": {
            "ventana_dias": config.window_days, "nivel_servicio": config.service_level,
            "z_score": round(z_score, 6), "peso_estacional": config.seasonal_weight,
            "dias_revision": config.review_days,
            "demanda": "FACTURA: unidades_vendidas + unidades_bonificadas; NC excluidas del pronóstico",
        },
        "orden_sugerida": rows, "resumen_proveedores": suppliers, "advertencias": warnings,
    }
