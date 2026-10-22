"""Regresiones P0: claves desordenadas, precios y límites visibles en la API."""

from decimal import Decimal
import unittest
from unittest.mock import patch

import httpx
import pandas as pd

import main
from dashboard import build_dashboard_metrics
from engine import EngineInputError, generate_suggested_order
from integrity import join_catalog
from stock_policy import coverage_metrics
from test_engine import engine_tables
from test_ingest import uploads


def two_skus():
    tables = engine_tables()
    sales, catalog, inventory = (tables[name] for name in main.SCHEMAS)
    sales["sku_id"] = "SKU-1000"
    catalog.loc[0, ["sku_id", "nombre_producto"]] = ["SKU-1000", "Producto 1000"]
    catalog["costo_unitario_usd"] = 2.35
    inventory["sku_id"] = "SKU-1000"
    other_sales = sales.assign(sku_id="SKU-1009", unidades_vendidas=2, venta_neta_usd=30)
    other_catalog = catalog.assign(
        sku_id="SKU-1009", nombre_producto="Producto 1009", ean="9780201379624",
        costo_unitario_usd=7.44, precio_lista_usd=15, unidades_por_caja=6,
        lead_time_dias=7, clasificacion_abc="B",
    )
    other_stock = inventory.assign(sku_id="SKU-1009", stock_disponible=5)
    tables["ventas_historicas"] = pd.concat([sales, other_sales], ignore_index=True)
    tables["catalogo_sku"] = pd.concat([catalog, other_catalog], ignore_index=True)
    tables["inventario_actual"] = pd.concat([inventory, other_stock], ignore_index=True)
    return tables


def calculate(function, tables):
    return function(*(tables[name] for name in main.SCHEMAS))


class IntegrityTests(unittest.TestCase):
    def test_sku_1000_and_1009_never_exchange_stock_demand_or_cost(self):
        tables = two_skus()
        for seed in range(3):
            with self.subTest(seed=seed):
                scrambled = {name: frame.sample(frac=1, random_state=seed).copy() for name, frame in tables.items()}
                # Índices repetidos y ajenos al orden de los SKU en cada libro.
                for frame in scrambled.values():
                    frame.index = [17] * len(frame)
                rows = {row["sku_id"]: row for row in calculate(generate_suggested_order, scrambled)["orden_sugerida"]}
                for sku, stock, demand, units, cost in [
                    ("SKU-1000", 10, 10, 48, 112.80),
                    ("SKU-1009", 5, 2, 12, 89.28),
                ]:
                    row = rows[sku]
                    self.assertEqual(row["stock_disponible"], stock)
                    self.assertEqual(row["demanda_diaria_ponderada"], demand)
                    self.assertEqual(row["cantidad_sugerida_unidades"], units)
                    self.assertEqual(row["costo_total_usd"], cost)
                    self.assertEqual(row["nombre_producto"], f"Producto {sku[4:]}")

    def test_dashboard_margin_and_exposure_follow_sku_not_index(self):
        tables = two_skus()
        tables["inventario_actual"].loc[1, "stock_disponible"] = 2000
        expected = calculate(build_dashboard_metrics, tables)
        for name, frame in tables.items():
            tables[name] = frame.iloc[::-1].copy()
            tables[name].index = [31] * len(frame)
        self.assertEqual(calculate(build_dashboard_metrics, tables), expected)
        rows = {row["sku_id"]: row for row in expected["detalle_skus"]}
        self.assertEqual(rows["SKU-1000"]["estado_salud"], "quiebre")
        self.assertEqual(rows["SKU-1009"]["capital_sobreinventario_usd"], 13540.80)
        self.assertEqual(rows["SKU-1009"]["margen_estimado_periodo_usd"], 907.20)

    def test_join_preserves_left_rows_and_checks_many_to_one(self):
        tables = two_skus()
        inventory = tables["inventario_actual"].iloc[::-1].copy()
        inventory.index = [88, 88]
        joined = join_catalog(inventory, tables["catalogo_sku"], ["costo_unitario_usd"])
        self.assertEqual(joined.sku_id.tolist(), ["SKU-1009", "SKU-1000"])
        self.assertEqual(joined.costo_unitario_usd.tolist(), [7.44, 2.35])
        self.assertEqual(joined.index.tolist(), [88, 88])
        self.assertNotIn("costo_unitario_usd", inventory.columns)

    def test_direct_engines_reject_ambiguous_catalog_unknown_keys_and_duplicate_lots(self):
        for function in [generate_suggested_order, build_dashboard_metrics]:
            for problem in ["SKU_DUPLICADO", "SKU_DESCONOCIDO", "LOTE_DUPLICADO", "SKU_INVALIDO"]:
                with self.subTest(function=function.__name__, problem=problem):
                    tables = two_skus()
                    if problem == "SKU_DUPLICADO":
                        tables["catalogo_sku"].loc[1, "sku_id"] = "SKU-1000"
                    elif problem == "SKU_DESCONOCIDO":
                        tables["ventas_historicas"].loc[0, "sku_id"] = "NO-EXISTE"
                    elif problem == "SKU_INVALIDO":
                        tables["inventario_actual"].loc[0, "sku_id"] = None
                    else:
                        tables["inventario_actual"] = pd.concat([tables["inventario_actual"]] * 2, ignore_index=True)
                    with self.assertRaises(EngineInputError) as caught:
                        calculate(function, tables)
                    self.assertEqual(caught.exception.code, problem)

    def test_cost_is_units_times_catalog_cost_with_only_cent_rounding(self):
        tables = engine_tables()
        for cost in [0, 0.1, 2.345, 123.456789]:
            with self.subTest(cost=cost):
                tables["catalogo_sku"]["costo_unitario_usd"] = cost
                data = calculate(generate_suggested_order, tables)
                row = data["orden_sugerida"][0]
                expected = (Decimal(row["cantidad_sugerida_unidades"]) * Decimal(str(cost))).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
                self.assertEqual(Decimal(str(row["costo_total_usd"])), expected)
                self.assertEqual(data["resumen_proveedores"][0]["costo_total_usd"], row["costo_total_usd"])

    def test_coverage_threshold_uses_same_visible_value_and_flag_in_both_engines(self):
        tables = engine_tables()
        for stock in [899, 900, 901]:
            with self.subTest(stock=stock):
                tables["inventario_actual"].loc[0, "stock_disponible"] = stock
                dashboard = calculate(build_dashboard_metrics, tables)
                detail = dashboard["detalle_skus"][0]
                order = calculate(generate_suggested_order, tables)["orden_sugerida"][0]
                self.assertEqual(detail["cobertura_dias"], stock / 10)
                self.assertEqual(order["cobertura_dias"], detail["cobertura_dias"])
                self.assertEqual(detail["sobreinventario"], detail["cobertura_dias"] > 90)
                self.assertEqual(order["sobreinventario"], detail["sobreinventario"])
                self.assertEqual(dashboard["salud_catalogo"]["exceso"], int(detail["sobreinventario"]))
                self.assertEqual(detail["capital_sobreinventario_usd"], max(0, stock - 900))

    def test_binary_noise_at_90_days_does_not_create_excess(self):
        for mean in [10 - 1e-12, 10, 10 + 1e-12]:
            self.assertEqual(coverage_metrics(900, mean), dict(days=90.0, excess=0.0, overstock=False))
        # Un exceso real pequeño sigue siendo visible; no se redondea a 90.00.
        above = coverage_metrics(900, 900 / 90.004)
        self.assertEqual(above["days"], 90.004)
        self.assertTrue(above["overstock"])
        self.assertGreater(above["excess"], 0)

    def test_near_zero_shortage_and_rop_share_precision_with_warning(self):
        tables = engine_tables()
        tables["inventario_actual"].loc[0, "stock_disponible"] = 50
        tables["catalogo_sku"].loc[0, "costo_unitario_usd"] = 1_000_000_000
        original_forecast = __import__("engine").DemandProfile.forecast
        for noise in [1e-10, 0.0001]:
            with self.subTest(noise=noise):
                def forecast(profile, cutoff, days):
                    return [value + noise for value in original_forecast(profile, cutoff, days)]
                with patch("engine.DemandProfile.forecast", forecast):
                    order = calculate(generate_suggested_order, tables)
                    dashboard = calculate(build_dashboard_metrics, tables)
                row = order["orden_sugerida"][0]
                self.assertEqual(row["bajo_punto_reorden"], row["punto_reorden"] > row["posicion_inventario_lead_time"])
                self.assertEqual(row["riesgo_quiebre_antes_recepcion"], row["demanda_no_cubierta_antes_recepcion"] > 0)
                self.assertEqual(row["riesgo_quiebre_antes_recepcion"], any(w["codigo"] == "RIESGO_QUIEBRE_ANTES_RECEPCION" for w in order["advertencias"]))
                self.assertEqual(row["cantidad_sugerida_cajas"] > 0, noise > 1e-6)
                detail = dashboard["detalle_skus"][0]
                self.assertEqual(detail["riesgo_quiebre_14_dias"], detail["demanda_no_cubierta_14_dias"] > 0)
                self.assertEqual(dashboard["salud_catalogo"]["quiebre"], int(detail["riesgo_quiebre_14_dias"]))

    def test_no_phantom_risk_value_for_zero_published_shortage(self):
        tables = engine_tables()
        tables["inventario_actual"].loc[0, "stock_disponible"] = 140
        tables["catalogo_sku"].loc[0, "precio_lista_usd"] = 1_000_000_000
        with patch("engine.DemandProfile.forecast", return_value=[10.0000000001] * 14):
            result = calculate(build_dashboard_metrics, tables)
        row = result["detalle_skus"][0]
        self.assertEqual(row["demanda_no_cubierta_14_dias"], 0)
        self.assertFalse(row["riesgo_quiebre_14_dias"])
        self.assertEqual(result["venta_riesgo_quiebre_usd"], 0)
        self.assertEqual(result["salud_catalogo"]["quiebre"], 0)


class IntegrityEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_catalog_is_422_in_etl_ocs_and_dashboard(self):
        tables = two_skus()
        tables["catalogo_sku"].loc[1, "sku_id"] = "  SKU-1000  "
        files = uploads(tables)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            for endpoint in ["/api/v1/ingest/validate", "/api/v1/replenishment/suggested-order", "/api/v1/dashboard/metrics"]:
                with self.subTest(endpoint=endpoint):
                    response = await client.post(endpoint, files=files)
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn("SKU_DUPLICADO", {error["codigo"] for error in response.json()["errores"]})

    async def test_multiple_lots_and_repeated_sales_skus_remain_valid(self):
        tables = two_skus()
        second_lot = tables["inventario_actual"].iloc[[0]].assign(lote="OTRO-LOTE", stock_disponible=12)
        tables["inventario_actual"] = pd.concat([tables["inventario_actual"], second_lot], ignore_index=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            for endpoint in ["/api/v1/ingest/validate", "/api/v1/replenishment/suggested-order", "/api/v1/dashboard/metrics"]:
                with self.subTest(endpoint=endpoint):
                    response = await client.post(endpoint, files=uploads(tables))
                    self.assertEqual(response.status_code, 200, response.text)

    async def test_extra_columns_do_not_override_catalog_cost_or_case_size(self):
        tables = two_skus()
        tables["ventas_historicas"]["costo_unitario_usd"] = 99999
        tables["inventario_actual"]["unidades_por_caja"] = 99999
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            for endpoint in ["/api/v1/ingest/validate", "/api/v1/replenishment/suggested-order", "/api/v1/dashboard/metrics"]:
                with self.subTest(endpoint=endpoint):
                    response = await client.post(endpoint, files=uploads(tables))
                    self.assertEqual(response.status_code, 200, response.text)
                    if "orden_sugerida" in response.json():
                        row = response.json()["orden_sugerida"][0]
                        self.assertEqual(row["costo_total_usd"], 112.8)
                        self.assertEqual(row["unidades_por_caja"], 12)
                    if "detalle_skus" in response.json():
                        self.assertEqual(response.json()["detalle_skus"][0]["margen_estimado_periodo_usd"], -210)


if __name__ == "__main__":
    unittest.main()
