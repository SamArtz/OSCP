"""Pruebas numéricas y funcionales del motor de reabastecimiento."""

import math
import tempfile
import unittest
from pathlib import Path
from statistics import NormalDist
from unittest.mock import patch

import httpx
import pandas as pd

import main
from engine import (
    EngineInputError, ReplenishmentConfig, demand_profile, generate_suggested_order,
)
from test_ingest import fixtures, uploads


def engine_tables():
    tables = fixtures()
    cutoff = pd.Timestamp("2026-10-21")
    template = tables["ventas_historicas"].iloc[0].to_dict()
    rows = []
    for number, day in enumerate(pd.date_range(cutoff - pd.Timedelta(days=60), periods=60)):
        rows.append({**template, "fecha_factura": day, "id_documento": f"F-{number}",
                     "unidades_vendidas": 10, "unidades_bonificadas": 0, "venta_neta_usd": 20})
    tables["ventas_historicas"] = pd.DataFrame(rows)
    tables["catalogo_sku"].loc[0, "moq_cajas"] = 2
    tables["inventario_actual"].loc[0, "stock_disponible"] = 10
    for field in ["fecha_corte", "fecha_llegada_transito", "fecha_vencimiento_lote"]:
        tables["inventario_actual"][field] = pd.to_datetime(tables["inventario_actual"][field])
    return tables


def run_engine(tables, config=None):
    return generate_suggested_order(*(tables[key] for key in main.SCHEMAS), config=config)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tables = engine_tables()
        self.cutoff = pd.Timestamp("2026-10-21")

    def result(self, config=None):
        return run_engine(self.tables, config)

    def row(self, config=None):
        return self.result(config)["orden_sugerida"][0]

    def add_transit(self, offset, quantity=24):
        inventory = self.tables["inventario_actual"]
        inventory.loc[0, "stock_en_transito"] = quantity
        inventory.loc[0, "oc_transito_id"] = "OC-1"
        inventory.loc[0, "fecha_llegada_transito"] = self.cutoff + pd.Timedelta(days=offset)

    def test_constant_demand_rop_boxes_and_cost(self):
        row = self.row()
        self.assertAlmostEqual(row["demanda_diaria_ponderada"], 10)
        self.assertEqual(row["pronostico_demanda_lead_time"], 50)
        self.assertEqual(row["stock_seguridad"], 0)
        self.assertEqual(row["punto_reorden"], 50)
        self.assertEqual(row["cantidad_sugerida_cajas"], 4)
        self.assertEqual(row["cantidad_sugerida_unidades"], 48)
        self.assertEqual(row["costo_total_usd"], 48)

    def test_moq_applies_only_to_positive_purchase(self):
        self.tables["catalogo_sku"].loc[0, "moq_cajas"] = 20
        self.assertEqual(self.row()["cantidad_sugerida_cajas"], 20)
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = 500
        self.assertEqual(self.row()["cantidad_sugerida_cajas"], 0)

    def test_exact_box_boundary_is_not_rounded_up_again(self):
        self.tables["catalogo_sku"].loc[0, "lead_time_dias"] = 6
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = 0
        self.assertEqual(self.row()["cantidad_sugerida_cajas"], 5)

    def test_recent_days_have_more_weight(self):
        dates = pd.date_range(self.cutoff - pd.Timedelta(days=30), periods=30)
        profile = demand_profile(pd.Series([10] * 15 + [20] * 15, index=dates), self.cutoff,
                                 ReplenishmentConfig(window_days=30, seasonal_weight=0))
        self.assertAlmostEqual(profile.mean, (10 * 120 + 20 * 345) / 465)

    def test_missing_calendar_days_are_zero_not_ignored(self):
        history = pd.Series([30, 30], index=[self.cutoff - pd.Timedelta(days=30), self.cutoff - pd.Timedelta(days=1)])
        profile = demand_profile(history, self.cutoff, ReplenishmentConfig(window_days=30))
        self.assertEqual(len(profile.daily), 30)
        self.assertEqual(profile.daily.eq(0).sum(), 28)
        self.assertAlmostEqual(profile.mean, 2)

    def test_weekly_seasonality_changes_forecast(self):
        cutoff = pd.Timestamp("2026-10-19")  # lunes
        dates = pd.date_range(cutoff - pd.Timedelta(days=56), periods=56)
        history = pd.Series([70 if day.dayofweek == 0 else 0 for day in dates], index=dates)
        profile = demand_profile(history, cutoff, ReplenishmentConfig(seasonal_weight=1))
        forecast = profile.forecast(cutoff, 7)
        self.assertTrue(profile.seasonal)
        self.assertGreater(forecast[0], 0)
        self.assertEqual(forecast[1:], [0] * 6)
        self.assertAlmostEqual(sum(forecast), profile.mean * 7)
        self.assertAlmostEqual(profile.total(cutoff, 7300), sum(profile.forecast(cutoff, 7300)))

    def test_old_sales_do_not_fill_a_recent_window_with_stale_demand(self):
        history = pd.Series([100], index=[self.cutoff - pd.Timedelta(days=100)])
        profile = demand_profile(history, self.cutoff, ReplenishmentConfig())
        self.assertEqual(len(profile.daily), 60)
        self.assertEqual(profile.mean, 0)

    def test_new_sku_short_history_falls_back_without_prelaunch_zeros(self):
        dates = pd.date_range(self.cutoff - pd.Timedelta(days=10), periods=10)
        profile = demand_profile(pd.Series(10, index=dates), self.cutoff, ReplenishmentConfig())
        self.assertEqual(len(profile.daily), 10)
        self.assertFalse(profile.seasonal)
        self.assertEqual(profile.mean, 10)

    def test_safety_stock_uses_normal_quantile_and_sqrt_lead(self):
        sales = self.tables["ventas_historicas"]
        sales["unidades_vendidas"] = [10, 20] * 30
        row = self.row(ReplenishmentConfig(seasonal_weight=0))
        expected = NormalDist().inv_cdf(0.95) * row["desviacion_diaria_residual"] * math.sqrt(5)
        self.assertGreater(row["stock_seguridad"], 0)
        self.assertAlmostEqual(row["stock_seguridad"], expected, places=5)
        self.assertAlmostEqual(row["punto_reorden"], row["pronostico_demanda_lead_time"] + row["stock_seguridad"], places=5)

    def test_bonus_is_demand_but_credit_is_not_negative_demand(self):
        sales = self.tables["ventas_historicas"]
        sales["unidades_bonificadas"] = 2
        credit = sales.iloc[-1].to_dict()
        credit.update(id_documento="NC-1", tipo_doc="NOTA_CREDITO", unidades_vendidas=-1000,
                      unidades_bonificadas=-100, venta_neta_usd=-2000, motivo_nc="Devolución Calidad")
        self.tables["ventas_historicas"] = pd.concat([sales, pd.DataFrame([credit])], ignore_index=True)
        self.assertEqual(self.row()["demanda_diaria_ponderada"], 12)

    def test_no_future_or_same_day_leakage(self):
        base = self.row()
        future = self.tables["ventas_historicas"].iloc[-1].to_dict()
        future.update(id_documento="FUTURE", fecha_factura=self.cutoff, unidades_vendidas=100000)
        self.tables["ventas_historicas"] = pd.concat([self.tables["ventas_historicas"], pd.DataFrame([future])], ignore_index=True)
        self.assertEqual(self.row()["punto_reorden"], base["punto_reorden"])
        self.assertIn("VENTAS_DESDE_CORTE_EXCLUIDAS", {w["codigo"] for w in self.result()["advertencias"]})

    def test_transit_on_time_reduces_purchase(self):
        self.add_transit(2)
        row = self.row()
        self.assertEqual(row["stock_en_transito_a_tiempo"], 24)
        self.assertEqual(row["cantidad_sugerida_cajas"], 2)

    def test_transit_at_lead_boundary_counts_but_warns_about_prior_shortage(self):
        self.add_transit(5)
        result = self.result()
        self.assertEqual(result["orden_sugerida"][0]["cantidad_sugerida_cajas"], 2)
        self.assertIn("RIESGO_QUIEBRE_ANTES_RECEPCION", {w["codigo"] for w in result["advertencias"]})

    def test_transit_late_and_overdue_do_not_hide_shortages(self):
        for offset, key in [(6, "stock_en_transito_fuera_horizonte"), (-1, "stock_en_transito_atrasado")]:
            with self.subTest(offset=offset):
                self.add_transit(offset, 1000)
                row = self.row()
                self.assertEqual(row[key], 1000)
                self.assertEqual(row["stock_en_transito_a_tiempo"], 0)
                self.assertEqual(row["cantidad_sugerida_cajas"], 4)

    def test_ambiguous_repeated_transit_is_rejected(self):
        self.add_transit(2)
        inventory = pd.concat([self.tables["inventario_actual"]] * 2, ignore_index=True)
        inventory.loc[1, "lote"] = "LOTE-2"
        self.tables["inventario_actual"] = inventory
        with self.assertRaises(EngineInputError) as context:
            self.result()
        self.assertEqual(context.exception.code, "TRANSITO_OC_AMBIGUO")

    def test_expired_stock_is_excluded(self):
        self.tables["inventario_actual"].loc[0, "fecha_vencimiento_lote"] = self.cutoff - pd.Timedelta(days=1)
        row = self.row()
        self.assertEqual(row["stock_disponible"], 10)
        self.assertEqual(row["stock_utilizable"], 0)
        self.assertEqual(row["stock_vencido_excluido"], 10)
        self.assertEqual(row["cantidad_sugerida_cajas"], 5)

    def test_transit_does_not_inherit_current_lot_expiry(self):
        self.tables["inventario_actual"].loc[0, "fecha_vencimiento_lote"] = self.cutoff - pd.Timedelta(days=1)
        self.add_transit(2)
        row = self.row()
        self.assertEqual(row["stock_vencido_excluido"], 10)
        self.assertEqual(row["merma_proyectada_fefo"], 0)
        self.assertEqual(row["stock_en_transito_a_tiempo"], 24)
        self.assertEqual(row["cantidad_sugerida_cajas"], 3)

    def test_fefo_consumes_earliest_lot_first(self):
        inventory = pd.concat([self.tables["inventario_actual"]] * 2, ignore_index=True)
        inventory.loc[0, ["lote", "stock_disponible", "fecha_vencimiento_lote"]] = ["LATE", 100, self.cutoff + pd.Timedelta(days=100)]
        inventory.loc[1, ["lote", "stock_disponible", "fecha_vencimiento_lote"]] = ["EARLY", 10, self.cutoff]
        self.tables["inventario_actual"] = inventory
        row = self.row()
        self.assertEqual(row["prioridad_fefo"][0]["lote"], "EARLY")
        self.assertEqual(row["prioridad_fefo"][0]["consumo_estimado_unidades"], 10)
        self.assertEqual(row["merma_proyectada_fefo"], 0)
        self.assertEqual(row["cantidad_sugerida_cajas"], 0)

    def test_expiry_during_lead_only_removes_unconsumed_remainder(self):
        inventory = self.tables["inventario_actual"]
        inventory.loc[0, "stock_disponible"] = 100
        inventory.loc[0, "fecha_vencimiento_lote"] = self.cutoff + pd.Timedelta(days=1)
        row = self.row()
        self.assertEqual(row["merma_proyectada_fefo"], 80)
        self.assertEqual(row["prioridad_fefo"][0]["consumo_estimado_unidades"], 20)
        self.assertEqual(row["cantidad_sugerida_cajas"], 3)

    def test_discontinued_sku_is_not_ordered(self):
        self.tables["catalogo_sku"].loc[0, "estado"] = "DESCONTINUADO"
        self.assertEqual(self.row()["cantidad_sugerida_cajas"], 0)
        self.assertEqual(self.row()["estado_sugerencia"], "DESCONTINUADO")

    def test_unknown_inventory_and_unknown_history_require_review(self):
        catalog = pd.concat([self.tables["catalogo_sku"]] * 2, ignore_index=True)
        catalog.loc[1, ["sku_id", "ean"]] = ["SKU-2", "9780201379624"]
        self.tables["catalogo_sku"] = catalog
        result = self.result()
        row = result["orden_sugerida"][1]
        self.assertIsNone(row["stock_disponible"])
        self.assertEqual(row["estado_sugerencia"], "INVENTARIO_DESCONOCIDO")
        self.assertEqual(row["cantidad_sugerida_cajas"], 0)
        self.tables["ventas_historicas"] = self.tables["ventas_historicas"].iloc[:0]
        self.assertEqual(self.row()["estado_sugerencia"], "SIN_HISTORIAL")

    def test_zero_lead_can_use_optional_review_horizon(self):
        self.tables["catalogo_sku"].loc[0, "lead_time_dias"] = 0
        self.assertEqual(self.row()["cantidad_sugerida_cajas"], 0)
        row = self.row(ReplenishmentConfig(review_days=7))
        self.assertEqual(row["punto_reorden"], 0)
        self.assertEqual(row["objetivo_cobertura_unidades"], 70)
        self.assertEqual(row["cantidad_sugerida_cajas"], 5)

    def test_supplier_totals_and_source_frames_are_preserved(self):
        originals = {key: value.copy(deep=True) for key, value in self.tables.items()}
        result = self.result()
        self.assertEqual(result["resumen_proveedores"][0]["costo_total_usd"], 48)
        self.assertEqual(result["resumen_proveedores"][0]["cantidad_total_cajas"], 4)
        for key, original in originals.items():
            pd.testing.assert_frame_equal(original, self.tables[key])

    def test_parameter_validation(self):
        for kwargs in [{"service_level": 1}, {"service_level": float("nan")}, {"seasonal_weight": 2}, {"window_days": 1}, {"review_days": -1}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ReplenishmentConfig(**kwargs)


class ReplenishmentEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tables = engine_tables()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(main, "DATA_DIR", Path(self.temp.name))
        self.path_patch.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.path_patch.stop()
        self.temp.cleanup()

    async def post(self, **kwargs):
        return await self.client.post("/api/v1/replenishment/suggested-order", files=uploads(self.tables), **kwargs)

    async def test_multipart_has_requested_columns(self):
        response = await self.post()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["estado"], "exito")
        row = data["orden_sugerida"][0]
        self.assertTrue({"proveedor_id", "sku_id", "nombre_producto", "stock_disponible",
                         "stock_en_transito", "lead_time_dias", "pronostico_demanda_lead_time",
                         "cantidad_sugerida_cajas", "costo_total_usd"}.issubset(row))
        self.assertEqual(row["cantidad_sugerida_cajas"], 4)

    async def test_local_mode_and_missing_files(self):
        response = await self.client.post("/api/v1/replenishment/suggested-order")
        self.assertEqual(response.status_code, 422)
        for name, (_, content, _) in uploads(self.tables).items():
            (Path(self.temp.name) / f"{name}.xlsx").write_bytes(content)
        response = await self.client.post("/api/v1/replenishment/suggested-order")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["orden_sugerida"][0]["cantidad_sugerida_cajas"], 4)

    async def test_invalid_etl_data_never_creates_orders(self):
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = -10
        response = await self.post()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["orden_sugerida"], [])
        self.assertIn("STOCK_NEGATIVO", {e["codigo"] for e in response.json()["errores"]})

    async def test_parameters_and_optional_review(self):
        response = await self.post(params={"ventana_dias": 30, "nivel_servicio": 0.9, "dias_revision": 7})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["parametros"]["ventana_dias"], 30)
        self.assertEqual(response.json()["orden_sugerida"][0]["objetivo_cobertura_unidades"], 120)
        for params in [{"nivel_servicio": 1}, {"nivel_servicio": "nan"}, {"ventana_dias": 29}, {"dias_revision": -1}]:
            with self.subTest(params=params):
                response = await self.post(params=params)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["orden_sugerida"], [])

    async def test_engine_validation_is_a_structured_error(self):
        self.tables["catalogo_sku"].loc[0, "lead_time_dias"] = 731
        response = await self.post()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errores"][0]["codigo"], "HORIZONTE_NO_SOPORTADO")


if __name__ == "__main__":
    unittest.main()
