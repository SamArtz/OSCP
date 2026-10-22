"""Pruebas de capital, riesgo temporal, lotes y clasificación financiera."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import pandas as pd

import main
from dashboard import abc_margin, build_dashboard_metrics
from test_engine import engine_tables
from test_ingest import uploads


class DashboardMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tables = engine_tables()
        self.cutoff = pd.Timestamp("2026-10-21")

    def result(self):
        return build_dashboard_metrics(*(self.tables[key] for key in main.SCHEMAS))

    def test_known_financial_values(self):
        data = self.result()
        self.assertEqual(data["capital_sobreinventario_usd"], 0)
        self.assertEqual(data["venta_riesgo_quiebre_usd"], 260)  # (14*10 - 10) * $2
        self.assertEqual(data["inventario_riesgo_vencimiento_usd"], 10)
        self.assertEqual(data["salud_catalogo"], dict(quiebre=1, exceso=0, optimo=0, sin_datos=0))
        self.assertEqual(data["detalle_skus"][0]["margen_estimado_periodo_usd"], 600)

    def test_capital_values_only_units_above_90_days(self):
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = 1000
        data = self.result()
        self.assertEqual(data["capital_sobreinventario_usd"], 100)  # no todo el stock de $1000
        self.assertEqual(data["detalle_skus"][0]["cobertura_dias"], 100)
        self.assertEqual(data["salud_catalogo"]["exceso"], 1)

    def test_90_day_boundary_is_not_excess(self):
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = 900
        self.assertEqual(self.result()["capital_sobreinventario_usd"], 0)
        self.assertEqual(self.result()["salud_catalogo"]["optimo"], 1)
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = 901
        self.assertEqual(self.result()["capital_sobreinventario_usd"], 1)

    def test_expiry_strict_120_day_boundary(self):
        for days, expected in [(119, 10), (120, 0), (0, 10), (-1, 10)]:
            with self.subTest(days=days):
                self.tables["inventario_actual"].loc[0, "fecha_vencimiento_lote"] = self.cutoff + pd.Timedelta(days=days)
                self.assertEqual(self.result()["inventario_riesgo_vencimiento_usd"], expected)

    def test_expiry_counts_lots_not_whole_sku(self):
        inventory = pd.concat([self.tables["inventario_actual"]] * 2, ignore_index=True)
        inventory.loc[0, "fecha_vencimiento_lote"] = self.cutoff + pd.Timedelta(days=119)
        inventory.loc[1, ["lote", "stock_disponible", "fecha_vencimiento_lote"]] = ["LONG-LIFE", 500, self.cutoff + pd.Timedelta(days=200)]
        self.tables["inventario_actual"] = inventory
        self.assertEqual(self.result()["inventario_riesgo_vencimiento_usd"], 10)

    def test_expired_stock_is_excluded_from_cover_but_exposed(self):
        self.tables["inventario_actual"].loc[0, "fecha_vencimiento_lote"] = self.cutoff - pd.Timedelta(days=1)
        data = self.result()
        self.assertEqual(data["inventario_vencido_usd"], 10)
        self.assertEqual(data["inventario_riesgo_vencimiento_usd"], 10)
        self.assertEqual(data["venta_riesgo_quiebre_usd"], 280)
        self.assertEqual(data["detalle_skus"][0]["stock_utilizable"], 0)

    def test_stock_expiring_today_can_cover_today(self):
        self.tables["inventario_actual"].loc[0, "fecha_vencimiento_lote"] = self.cutoff
        self.assertEqual(self.result()["venta_riesgo_quiebre_usd"], 260)
        self.assertEqual(self.result()["inventario_vencido_usd"], 0)

    def test_class_b_does_not_contribute_to_class_a_sales_risk(self):
        self.tables["catalogo_sku"].loc[0, "clasificacion_abc"] = "B"
        self.assertEqual(self.result()["venta_riesgo_quiebre_usd"], 0)
        self.assertEqual(self.result()["salud_catalogo"]["quiebre"], 1)

    def test_bonus_consumes_stock_without_inventing_sales_revenue(self):
        self.tables["ventas_historicas"]["unidades_bonificadas"] = 2
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = 0
        data = self.result()
        self.assertAlmostEqual(data["detalle_skus"][0]["demanda_diaria_promedio"], 12)
        self.assertEqual(data["venta_riesgo_quiebre_usd"], 280)  # no $336 por bonos gratuitos
        self.assertEqual(data["detalle_skus"][0]["margen_estimado_periodo_usd"], 480)

    def test_transit_timing_prevents_masking_lost_sales(self):
        inventory = self.tables["inventario_actual"]
        inventory.loc[0, "stock_en_transito"] = 500
        inventory.loc[0, "oc_transito_id"] = "OC-1"
        for eta, expected in [(0, 0), (10, 180), (14, 260), (15, 260), (-1, 260)]:
            with self.subTest(eta=eta):
                inventory.loc[0, "fecha_llegada_transito"] = self.cutoff + pd.Timedelta(days=eta)
                self.assertEqual(self.result()["venta_riesgo_quiebre_usd"], expected)

    def test_unknown_history_is_not_zero_demand(self):
        self.tables["ventas_historicas"] = self.tables["ventas_historicas"].iloc[:0]
        data = self.result()
        self.assertEqual(data["salud_catalogo"]["sin_datos"], 1)
        self.assertEqual(data["cobertura_calculo"]["skus_sin_estimacion_exceso"], 1)
        self.assertEqual(data["cobertura_calculo"]["skus_clase_a_sin_estimacion_quiebre"], 1)
        self.assertIsNone(data["detalle_skus"][0]["capital_sobreinventario_usd"])
        self.assertIsNone(data["detalle_skus"][0]["venta_riesgo_quiebre_usd"])
        self.assertEqual(sum(cell["cantidad"] for cell in data["matriz_abc"]), 0)
        self.assertEqual(data["skus_sin_clase_margen"], 1)

    def test_recent_zero_demand_marks_idle_stock_without_infinity(self):
        self.tables["ventas_historicas"]["fecha_factura"] -= pd.Timedelta(days=100)
        data = self.result()
        self.assertEqual(data["capital_sobreinventario_usd"], 10)
        self.assertEqual(data["salud_catalogo"]["exceso"], 1)
        self.assertTrue(data["detalle_skus"][0]["sin_demanda_reciente"])
        self.assertIsNone(data["detalle_skus"][0]["cobertura_dias"])
        json.dumps(data, allow_nan=False)

    def test_future_sales_do_not_change_risk_or_margin(self):
        future = self.tables["ventas_historicas"].iloc[-1].to_dict()
        future.update(fecha_factura=self.cutoff, unidades_vendidas=1_000_000, venta_neta_usd=2_000_000)
        self.tables["ventas_historicas"] = pd.concat([self.tables["ventas_historicas"], pd.DataFrame([future])], ignore_index=True)
        data = self.result()
        self.assertEqual(data["venta_riesgo_quiebre_usd"], 260)
        self.assertEqual(data["detalle_skus"][0]["margen_estimado_periodo_usd"], 600)

    def test_margin_normalizes_credit_sign_idempotently(self):
        base = self.tables["ventas_historicas"].copy()
        for sign in [-1, 1]:
            with self.subTest(sign=sign):
                credit = base.iloc[-1].to_dict()
                credit.update(tipo_doc="NOTA_CREDITO", unidades_vendidas=3 * sign, venta_neta_usd=6 * sign)
                self.tables["ventas_historicas"] = pd.concat([base, pd.DataFrame([credit])], ignore_index=True)
                self.assertEqual(self.result()["detalle_skus"][0]["margen_estimado_periodo_usd"], 597)

    def test_abc_thresholds_and_unknown_margin(self):
        classes = abc_margin({"top": 80, "middle": 15, "last": 5, "negative": -100, "zero": 0, "unknown": None})
        self.assertEqual(classes, {"top": "A", "middle": "B", "last": "C", "negative": "C", "zero": "C", "unknown": None})
        self.assertEqual(abc_margin({"only": 100})["only"], "A")

    def test_missing_inventory_does_not_become_optimal(self):
        catalog = pd.concat([self.tables["catalogo_sku"]] * 2, ignore_index=True)
        catalog.loc[1, ["sku_id", "ean"]] = ["SKU-2", "9780201379624"]
        self.tables["catalogo_sku"] = catalog
        data = self.result()
        self.assertEqual(data["total_skus"], 2)
        self.assertEqual(sum(data["salud_catalogo"].values()), 2)
        self.assertEqual(data["salud_catalogo"]["sin_datos"], 1)
        self.assertIsNone(data["detalle_skus"][1]["stock_utilizable"])
        self.assertEqual(sum(cell["cantidad"] for cell in data["matriz_abc"]) + data["skus_sin_clase_margen"], 2)

    def test_inputs_are_unchanged(self):
        originals = {key: value.copy(deep=True) for key, value in self.tables.items()}
        self.result()
        for key, original in originals.items():
            pd.testing.assert_frame_equal(original, self.tables[key])


class DashboardEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tables = engine_tables()
        self.files = uploads(self.tables)
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.path_patch = patch.object(main, "DATA_DIR", self.directory)
        self.path_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.path_patch.stop()
        self.temp.cleanup()

    async def test_get_reads_local_files_and_matches_multipart(self):
        for name, (_, content, _) in self.files.items():
            (self.directory / f"{name}.xlsx").write_bytes(content)
        response = await self.client.get("/api/v1/dashboard/metrics")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["estado"], "exito")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["venta_riesgo_quiebre_usd"], 260)
        uploaded = await self.client.post("/api/v1/dashboard/metrics", files=self.files)
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["detalle_skus"], response.json()["detalle_skus"])

    async def test_missing_files_are_errors_not_zero_metrics(self):
        response = await self.client.get("/api/v1/dashboard/metrics")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["estado"], "error")
        self.assertNotIn("capital_sobreinventario_usd", response.json())

    async def test_invalid_schema_does_not_return_metrics(self):
        self.tables["catalogo_sku"] = self.tables["catalogo_sku"].drop(columns="costo_unitario_usd")
        response = await self.client.post("/api/v1/dashboard/metrics", files=uploads(self.tables))
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("venta_riesgo_quiebre_usd", response.json())

    async def test_parameters_and_get_cors(self):
        response = await self.client.post("/api/v1/dashboard/metrics?ventana_dias=29", files=self.files)
        self.assertEqual(response.status_code, 422)
        response = await self.client.post("/api/v1/dashboard/metrics?ventana_dias=30", files=self.files)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["parametros"]["ventana_dias"], 30)
        preflight = await self.client.options("/api/v1/dashboard/metrics", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
        self.assertEqual(preflight.status_code, 200)


if __name__ == "__main__":
    unittest.main()
