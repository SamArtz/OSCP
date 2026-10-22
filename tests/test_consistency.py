"""Regresiones de identidad, salud compartida y trazabilidad del baseline."""

from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch

import httpx
import pandas as pd

import main
from dashboard import build_dashboard_metrics
from engine import EngineInputError, ReplenishmentConfig, generate_suggested_order, price_suggested_lines
from integrity import catalog_with_inventory
from stock_policy import calcular_estado_sku, count_sku_states
from test_engine import engine_tables
from test_ingest import uploads
from test_integrity import two_skus


def calculate(function, tables, config=None):
    return function(*(tables[name] for name in main.SCHEMAS), config=config)


class ConsistencyTests(unittest.TestCase):
    def test_pricing_discards_corrupt_intermediate_prices_and_keeps_rows_intact(self):
        catalog = two_skus()["catalogo_sku"].iloc[::-1].copy()
        catalog.index = [99, 99]
        rows = [
            {"sku_id": "SKU-1000", "cantidad_sugerida_unidades": 48, "costo_unitario_usd": 9999, "costo_total_usd": 99999, "stock_disponible": None},
            {"sku_id": "SKU-1009", "cantidad_sugerida_unidades": 12, "costo_unitario_usd": 2.35, "costo_total_usd": 0, "stock_disponible": 5},
        ]
        result = price_suggested_lines(rows, catalog)
        self.assertEqual([row["costo_unitario_usd"] for row in result], [2.35, 7.44])
        self.assertEqual([row["costo_total_usd"] for row in result], [112.8, 89.28])
        self.assertIsNone(result[0]["stock_disponible"])
        self.assertEqual(rows[0]["costo_unitario_usd"], 9999)

    def test_engine_prices_from_original_catalog_despite_corrupted_enriched_master(self):
        tables = two_skus()
        corrupted = catalog_with_inventory(tables["catalogo_sku"], tables["inventario_actual"])
        corrupted["costo_unitario_usd"] = 999999
        with patch("engine.catalog_with_inventory", return_value=corrupted):
            data = calculate(generate_suggested_order, tables)
        self.assertEqual([row["costo_total_usd"] for row in data["orden_sugerida"]], [112.8, 89.28])
        self.assertEqual(data["resumen_proveedores"][0]["costo_total_usd"], 202.08)

    def test_pricing_rejects_ambiguous_or_unknown_sku(self):
        tables = two_skus()
        row = {"sku_id": "SKU-1000", "cantidad_sugerida_unidades": 48}
        for rows, expected in [([row, row], "SKU_DUPLICADO"), ([{**row, "sku_id": "NO-EXISTE"}], "SKU_DESCONOCIDO")]:
            with self.subTest(expected=expected):
                with self.assertRaises(EngineInputError) as caught:
                    price_suggested_lines(rows, tables["catalogo_sku"])
                self.assertEqual(caught.exception.code, expected)

    def test_all_health_signals_use_14_days_even_when_lead_is_longer(self):
        tables = engine_tables()
        tables["catalogo_sku"]["lead_time_dias"] = 30
        tables["inventario_actual"]["stock_disponible"] = 200
        order = calculate(generate_suggested_order, tables)
        dashboard = calculate(build_dashboard_metrics, tables)
        row = order["orden_sugerida"][0]
        self.assertTrue(row["riesgo_quiebre_antes_recepcion"])
        self.assertFalse(row["riesgo_quiebre_14_dias"])
        self.assertEqual(row["estado_salud"], "optimo")
        self.assertEqual(order["salud_catalogo"], dashboard["salud_catalogo"])
        self.assertEqual(order["salud_catalogo"]["quiebre"], 0)
        self.assertNotIn("RIESGO_QUIEBRE_14_DIAS", {w["codigo"] for w in order["advertencias"]})

    def test_zero_stock_discontinued_and_missing_history_share_health(self):
        for state, no_history in [("DESCONTINUADO", False), ("ACTIVO", True)]:
            with self.subTest(state=state, no_history=no_history):
                tables = engine_tables()
                tables["catalogo_sku"]["estado"] = state
                tables["inventario_actual"]["stock_disponible"] = 0
                if no_history:
                    tables["ventas_historicas"] = tables["ventas_historicas"].iloc[:0]
                order = calculate(generate_suggested_order, tables)
                dashboard = calculate(build_dashboard_metrics, tables)
                self.assertEqual(order["orden_sugerida"][0]["estado_salud"], "quiebre")
                self.assertEqual(order["salud_catalogo"], dashboard["salud_catalogo"])
                self.assertEqual(order["salud_catalogo"]["quiebre"], 1)

    def test_state_priority_and_90_day_boundary_are_centralized(self):
        for stock, demand, uncovered, expected in [
            (None, 10, None, "sin_datos"), (10, None, None, "sin_datos"),
            (0, None, None, "quiebre"), (900, 10, 0, "optimo"),
            (901, 10, 0, "exceso"), (1000, 10, 1, "quiebre"),
            (10, 0, 0, "exceso"), (0, 0, 0, "quiebre"),
        ]:
            with self.subTest(stock=stock, demand=demand, uncovered=uncovered):
                self.assertEqual(calcular_estado_sku(stock, demand, uncovered)["estado_salud"], expected)

    def test_sku_1029_physical_stock_is_never_replaced_by_transit(self):
        tables = two_skus()
        catalog = tables["catalogo_sku"].iloc[[0]].assign(sku_id="SKU-1029", costo_unitario_usd=0.73, lead_time_dias=15)
        stock = tables["inventario_actual"].iloc[[0]].assign(
            sku_id="SKU-1029", stock_disponible=50, stock_en_transito=480,
            oc_transito_id="OC-1029", fecha_llegada_transito=pd.Timestamp("2026-11-05"),
        )
        second = stock.assign(lote="SEGUNDO", stock_disponible=70, stock_en_transito=0, oc_transito_id=None, fecha_llegada_transito=pd.NaT)
        sales = tables["ventas_historicas"].loc[lambda frame: frame.sku_id.eq("SKU-1000")].assign(sku_id="SKU-1029")
        tables["catalogo_sku"] = pd.concat([tables["catalogo_sku"], catalog], ignore_index=True)
        tables["inventario_actual"] = pd.concat([tables["inventario_actual"], stock, second], ignore_index=True)
        tables["ventas_historicas"] = pd.concat([tables["ventas_historicas"], sales], ignore_index=True)
        for name, frame in tables.items():
            tables[name] = frame.sample(frac=1, random_state=7).copy()
            tables[name].index = [123] * len(frame)
        for function, key in [(generate_suggested_order, "orden_sugerida"), (build_dashboard_metrics, "detalle_skus")]:
            data = calculate(function, tables)
            row = next(row for row in data[key] if row["sku_id"] == "SKU-1029")
            self.assertEqual(row["stock_disponible"], 120)
            self.assertEqual(row["stock_en_transito"], 480)
            self.assertEqual(data["salud_catalogo"], count_sku_states(data[key]))

    def test_inventory_columns_in_catalog_cannot_override_source(self):
        tables = two_skus()
        catalog = tables["catalogo_sku"].assign(stock_disponible=999999, stock_en_transito=999999)
        joined = catalog_with_inventory(catalog, tables["inventario_actual"])
        self.assertEqual(joined.stock_disponible.tolist(), [10, 5])
        self.assertEqual(joined.stock_en_transito.tolist(), [0, 0])

    def test_audit_operands_reproduce_weighted_and_seasonal_demand(self):
        tables = engine_tables()
        sales = tables["ventas_historicas"]
        sales["unidades_vendidas"] = [30 if day.dayofweek == 0 else 3 for day in sales.fecha_factura]
        for config in [ReplenishmentConfig(), ReplenishmentConfig(window_days=30, seasonal_weight=0)]:
            row = calculate(generate_suggested_order, tables, config)["orden_sugerida"][0]
            audit = row["auditoria_demanda"]
            self.assertEqual(audit["dias_observados"], config.window_days)
            self.assertAlmostEqual(audit["suma_demanda_por_peso"] / audit["suma_pesos"], audit["media_diaria_sin_redondear"])
            cutoff = pd.Timestamp("2026-10-21")
            forecast = sum(audit["media_diaria_sin_redondear"] * audit["factores_lunes_a_domingo"][(cutoff + timedelta(days=offset)).dayofweek] for offset in range(row["lead_time_dias"]))
            self.assertAlmostEqual(forecast, row["pronostico_demanda_lead_time"], places=6)
            dashboard = calculate(build_dashboard_metrics, tables, config)
            self.assertEqual(dashboard["detalle_skus"][0]["auditoria_demanda"], audit)


class ConsistencyEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_uploads_produce_identical_states_and_source_fingerprint(self):
        files = uploads(two_skus())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            order = (await client.post("/api/v1/replenishment/suggested-order", files=files)).json()
            dashboard = (await client.post("/api/v1/dashboard/metrics", files=files)).json()
        self.assertEqual(order["estado"], "exito", order)
        self.assertEqual(dashboard["estado"], "exito", dashboard)
        self.assertEqual(order["huella_datos"], dashboard["huella_datos"])
        self.assertEqual(order["salud_catalogo"], dashboard["salud_catalogo"])
        expected = {row["sku_id"]: row["estado_salud"] for row in dashboard["detalle_skus"]}
        self.assertEqual({row["sku_id"]: row["estado_salud"] for row in order["orden_sugerida"]}, expected)
        for row in order["orden_sugerida"]:
            self.assertEqual(Decimal(str(row["costo_total_usd"])), (Decimal(row["cantidad_sugerida_unidades"]) * Decimal(str(row["costo_unitario_usd"]))).quantize(Decimal(".01"), rounding="ROUND_HALF_UP"))


if __name__ == "__main__":
    unittest.main()
