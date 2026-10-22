"""Indicadores ejecutivos auditables sobre los DataFrames validados del ETL.

Los montos de inventario se valúan a costo actual; la venta en riesgo, a lista.
No se infiere demanda a partir del stock ni se confunde un SKU sin historia con
uno que registra demanda cero. Este módulo no modifica los datos recibidos.
"""

from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from engine import EngineInputError, ReplenishmentConfig, demand_profile, evaluate_sku_state
from integrity import catalog_with_inventory, join_catalog, validate_sku_integrity
from stock_policy import EXCESS_DAYS, RISK_DAYS, PRECISION, count_sku_states


def cents(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def abc_margin(contributions: dict[str, float | None]) -> dict[str, str | None]:
    """ABC por aporte positivo acumulado; el SKU que cruza el corte se incluye.

    El mayor contribuyente siempre es A. Márgenes cero/negativos son C; un margen
    desconocido queda sin clase y se informa fuera de las nueve celdas.
    """
    classes = {sku: None if value is None else "C" for sku, value in contributions.items()}
    positive = sorted(((sku, value) for sku, value in contributions.items() if value is not None and value > 0), key=lambda pair: (-pair[1], pair[0]))
    total = sum(value for _, value in positive)
    cumulative = 0.0
    for sku, value in positive:
        share_before = cumulative / total
        classes[sku] = "A" if share_before < 0.8 - 1e-12 else "B" if share_before < 0.95 - 1e-12 else "C"
        cumulative += value
    return classes


def build_dashboard_metrics(
    sales: pd.DataFrame,
    catalog: pd.DataFrame,
    inventory: pd.DataFrame,
    config: ReplenishmentConfig | None = None,
) -> dict:
    """Cobertura a 90 días, riesgo a 14 días y vencimiento estrictamente <120.

    Salud exclusiva: quiebre actual o proyectado en 14 días; luego exceso; luego
    óptimo. Los casos sin datos se separan y nunca se presentan como saludables.
    La exposición por KPI puede superponerse y no representa una pérdida contable.
    """
    config = config or ReplenishmentConfig()
    validate_sku_integrity(sales, catalog, inventory)
    cutoff = inventory.fecha_corte.iloc[0].normalize()
    if inventory.fecha_corte.nunique() != 1:
        raise EngineInputError("CORTES_MEZCLADOS", "El tablero requiere un único corte de inventario.")
    transit = inventory.loc[inventory.stock_en_transito.gt(0)]
    if transit.duplicated(["sku_id", "oc_transito_id"], keep=False).any():
        raise EngineInputError("TRANSITO_OC_AMBIGUO", "Consolide las líneas de tránsito OC/SKU repetidas antes de calcular el riesgo.")

    days = sales.fecha_factura.dt.normalize()
    invoices = sales.loc[sales.tipo_doc.eq("FACTURA") & days.lt(cutoff)].copy()
    invoices["day"] = invoices.fecha_factura.dt.normalize()
    invoices["physical"] = invoices.unidades_vendidas + invoices.unidades_bonificadas
    gross = invoices.groupby(["sku_id", "day"]).physical.sum()
    paid = invoices.groupby(["sku_id", "day"]).unidades_vendidas.sum()
    known_skus = set(invoices.sku_id)

    # El margen estimado netea NC de forma idempotente. Es una aproximación a
    # costo actual, no el margen contable histórico ni la recuperación de stock.
    recent = sales.loc[days.ge(cutoff - pd.Timedelta(days=config.window_days)) & days.lt(cutoff)].copy()
    is_credit = recent.tipo_doc.eq("NOTA_CREDITO")
    recent["net_revenue"] = recent.venta_neta_usd.where(~is_credit, -recent.venta_neta_usd.abs())
    recent["net_units"] = (
        recent.unidades_vendidas.where(~is_credit, -recent.unidades_vendidas.abs())
        + recent.unidades_bonificadas.where(~is_credit, -recent.unidades_bonificadas.abs())
    )
    # Cualquier columna adicional con ese nombre en ventas no sustituye al catálogo.
    recent = join_catalog(recent.drop(columns=["costo_unitario_usd"], errors="ignore"), catalog, ["costo_unitario_usd"])
    recent["margin"] = recent.net_revenue - recent.net_units * recent.costo_unitario_usd
    margin_sum = recent.groupby("sku_id").margin.sum()
    observed_skus = set(sales.loc[days.lt(cutoff), "sku_id"])
    contributions = {str(sku): float(margin_sum.get(sku, 0)) if sku in observed_skus else None for sku in catalog.sku_id}
    margin_classes = abc_margin(contributions)

    rows, warnings = [], []
    if inventory.bodega_id.nunique() > 1:
        warnings.append({"codigo": "STOCK_CONSOLIDADO", "mensaje": "Se consolidan bodegas asumiendo transferencias posibles; ventas no informa bodega."})
    if days.ge(cutoff).any():
        warnings.append({"codigo": "VENTAS_DESDE_CORTE_EXCLUIDAS", "mensaje": "Las ventas del día del corte o posteriores se excluyen del pronóstico y del margen reciente."})

    master = catalog_with_inventory(catalog, inventory)
    for item in master.sort_values("sku_id").itertuples(index=False):
        sku = str(item.sku_id)
        lots = inventory.loc[inventory.sku_id.eq(sku)]
        history = gross.loc[sku] if sku in known_skus else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        profile = demand_profile(history, cutoff, config)
        health_state, fefo = evaluate_sku_state(lots, profile, cutoff)
        available = fefo["usable_stock"] if not lots.empty else None
        # Cuenta exposición por lote, no por SKU: uno de sus lotes puede estar sano.
        life = (lots.fecha_vencimiento_lote.dt.normalize() - cutoff).dt.days
        expiry_units = int(lots.loc[life.lt(120), "stock_disponible"].sum())
        expired_units = int(lots.loc[life.lt(0), "stock_disponible"].sum())
        expiry_value = float(cents(expiry_units * item.costo_unitario_usd))
        expired_value = float(cents(expired_units * item.costo_unitario_usd))
        mean = profile.mean if profile else None
        excess_units = health_state["unidades_excedentes_90_dias"]
        excess_value = float(cents(excess_units * item.costo_unitario_usd)) if excess_units is not None else None
        # El riesgo es demanda no atendida en los días 0..13. Una llegada en el
        # día 14 no rescata ventas anteriores; FEFO evita contar stock vencido.
        uncovered = health_state["demanda_no_cubierta_14_dias"]
        paid_share = None
        risk_value = None
        if profile:
            paid_days = paid.loc[sku].reindex(profile.daily.index, fill_value=0)
            weights = pd.Series(range(1, len(profile.daily) + 1), index=profile.daily.index)
            total_physical = float((profile.daily * weights).sum())
            paid_share = float((paid_days * weights).sum()) / total_physical if total_physical > 0 else 0.0
        if item.clasificacion_abc == "A" and uncovered is not None:
            risk_value = float(cents(uncovered * paid_share * item.precio_lista_usd))
        elif item.clasificacion_abc != "A":
            risk_value = 0.0

        rows.append({
            **health_state,
            "sku_id": sku, "nombre_producto": str(item.nombre_producto),
            "proveedor_id": str(item.proveedor_id), "categoria": str(item.categoria), "marca": str(item.marca),
            "estado_sku": str(item.estado), "clase_volumen": str(item.clasificacion_abc),
            "clase_margen": margin_classes[sku], "margen_estimado_periodo_usd": float(cents(contributions[sku])) if contributions[sku] is not None else None,
            "stock_disponible": int(item.stock_disponible) if not lots.empty else None,
            "stock_en_transito": int(item.stock_en_transito) if not lots.empty else None,
            "stock_utilizable": available, "demanda_diaria_promedio": round(mean, 6) if mean is not None else None,
            "auditoria_demanda": profile.audit() if profile else None,
            "sin_demanda_reciente": mean == 0 if mean is not None else False,
            "sin_historial": profile is None,
            "capital_sobreinventario_usd": excess_value,
            "proporcion_unidades_pagadas": round(paid_share, 6) if paid_share is not None else None,
            "venta_riesgo_quiebre_usd": risk_value,
            "unidades_lotes_menos_120_dias": expiry_units, "inventario_riesgo_vencimiento_usd": expiry_value,
            "inventario_vencido_usd": expired_value,
        })

    matrix = [{"volumen": volume, "margen": margin, "cantidad": sum(row["clase_volumen"] == volume and row["clase_margen"] == margin for row in rows)} for volume in "ABC" for margin in "ABC"]
    def total(key):
        return float(sum((Decimal(str(row[key])) for row in rows if row[key] is not None), Decimal(0)))

    return {
        "fecha_corte": cutoff.date().isoformat(), "total_skus": len(rows),
        "capital_sobreinventario_usd": total("capital_sobreinventario_usd"),
        "venta_riesgo_quiebre_usd": total("venta_riesgo_quiebre_usd"),
        "inventario_riesgo_vencimiento_usd": total("inventario_riesgo_vencimiento_usd"),
        "inventario_vencido_usd": total("inventario_vencido_usd"),
        "salud_catalogo": count_sku_states(rows), "matriz_abc": matrix,
        "skus_sin_clase_margen": sum(row["clase_margen"] is None for row in rows),
        "cobertura_calculo": {
            "skus_sin_estimacion_exceso": sum(row["capital_sobreinventario_usd"] is None for row in rows),
            "skus_clase_a_sin_estimacion_quiebre": sum(row["clase_volumen"] == "A" and row["venta_riesgo_quiebre_usd"] is None for row in rows),
        },
        "parametros": {"ventana_dias": config.window_days, "dias_sobreinventario": EXCESS_DAYS, "dias_riesgo_quiebre": RISK_DAYS, "dias_riesgo_vencimiento": 120, "cortes_abc_margen": [0.8, 0.95], "decimales_cobertura_y_unidades": PRECISION},
        "criterios": {
            "capital": "Solo unidades utilizables por encima de 90 × demanda diaria ponderada, valoradas a costo actual; sin historial se excluyen.",
            "quiebre": "Venta a precio de lista de unidades pagadas no cubiertas en 14 días, solo clase A del catálogo; simula ETA y FEFO. No agrega impuestos ni flete.",
            "vencimiento": "Stock disponible de lotes con vida remanente estrictamente menor de 120 días, valorado a costo actual; incluye vencidos. Es exposición, no pérdida segura.",
            "salud": "Quiebre: stock utilizable cero o faltante proyectado en 14 días. Luego exceso >90 días. Óptimo: resto con demanda e inventario conocidos. Sin datos se separa.",
            "precision": "Cobertura y cantidades se normalizan a seis decimales antes de decidir indicadores y alertas; 90 días exactos no es exceso. Los contadores usan estado_salud, no recalculan desde valores formateados.",
            "abc": "Volumen: ABC del catálogo. Margen: aporte neto estimado de ventas recientes, a costo actual y con NC normalizadas; clases acumuladas 80%/95% sobre contribuciones positivas. Cero o negativo es C; desconocido queda fuera.",
            "margen": "Venta neta normalizada menos costo actual × (unidades vendidas netas + bonos netos). Aproximación de margen bruto, no margen contable histórico ni recuperación de devoluciones dañadas.",
            "alcance": "Fecha del inventario como inicio del día; demanda observada sin corregir censura. Incluye SKU descontinuados para no ocultar capital inmovilizado. Los indicadores pueden superponerse y no se suman como pérdida total.",
        },
        "advertencias": warnings, "detalle_skus": rows,
    }
