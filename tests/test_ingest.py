"""Pruebas funcionales con libros Excel pequeños, sin datos comerciales reales."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import pandas as pd

import main


def fixtures():
    sales = pd.DataFrame([
        dict(fecha_factura="2026-10-19", id_documento="FAC-1", cliente_id="C-1",
             sku_id="SKU-1", tipo_doc="FACTURA", canal="RUTEO", vendedor_id="V-1",
             unidades_vendidas=10, unidades_bonificadas=2, precio_unitario_usd=2,
             venta_neta_usd=20, motivo_nc="Ninguno"),
        dict(fecha_factura="2026-10-20", id_documento="NC-1", cliente_id="C-1",
             sku_id="SKU-1", tipo_doc="NOTA_CREDITO", canal="RUTEO", vendedor_id="V-1",
             unidades_vendidas=-3, unidades_bonificadas=0, precio_unitario_usd=2,
             venta_neta_usd=-6, motivo_nc="Devolución Calidad"),
    ])
    catalog = pd.DataFrame([dict(
        sku_id="SKU-1", sku_proveedor="REF-1", ean="4006381333931", nombre_producto="Producto",
        categoria="Alimentos", subcategoria="Galletas", marca="Marca", presentacion="Caja",
        proveedor_id="PROV-1", pais_origen="El Salvador", unidades_por_caja=12, moq_cajas=5,
        lead_time_dias=5, vida_util_dias=180, temperatura="Seco", costo_unitario_usd=1,
        precio_lista_usd=2, estado="ACTIVO", clasificacion_abc="A",
    )])
    inventory = pd.DataFrame([dict(
        fecha_corte="2026-10-21", bodega_id="BOD-1", sku_id="SKU-1", lote="LOTE-1",
        stock_disponible=0, stock_reservado=0, stock_danado=0, stock_en_transito=0,
        oc_transito_id=None, fecha_llegada_transito=None, fecha_vencimiento_lote="2027-01-01",
    )])
    return dict(ventas_historicas=sales, catalogo_sku=catalog, inventario_actual=inventory)


def excel(df, sheet):
    stream = io.BytesIO()
    df.to_excel(stream, index=False, sheet_name=sheet, engine="openpyxl")
    return stream.getvalue()


def uploads(tables):
    return {name: (f"{name}.xlsx", excel(df, main.SCHEMAS[name]["sheet"]),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            for name, df in tables.items()}


class IngestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")
        self.tables = fixtures()
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.path_patch = patch.object(main, "DATA_DIR", self.directory)
        self.path_patch.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.path_patch.stop()
        self.temp.cleanup()

    async def post(self, tables=None, **kwargs):
        return await self.client.post("/api/v1/ingest/validate", files=uploads(self.tables if tables is None else tables), **kwargs)

    def assert_error(self, response, code, status=422):
        self.assertEqual(response.status_code, status, response.text)
        body = response.json()
        self.assertEqual(body["estado"], "error")
        self.assertIn(code, {item["codigo"] for item in body["errores"]})
        self.assertEqual(body["preview"], {})

    async def test_negative_credit_bonus_and_stock(self):
        response = await self.post()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        totals = body["resumen_procesamiento"]["ventas"]
        self.assertEqual(totals["unidades_facturadas"], 10)
        self.assertEqual(totals["unidades_devueltas"], 3)
        self.assertEqual(totals["unidades_venta_netas"], 7)
        self.assertEqual(totals["unidades_bonificadas_netas"], 2)
        self.assertEqual(totals["unidades_salida_netas"], 9)
        self.assertEqual(totals["venta_neta_normalizada_usd"], 14)
        self.assertEqual(body["resumen"]["ventas_historicas"]["filas_leidas"], 2)
        self.assertEqual(body["resumen_procesamiento"]["inventario"]["sku_sin_stock"], ["SKU-1"])
        self.assertIsNone(body["preview"]["inventario_actual"][0]["fecha_llegada_transito"])
        self.assertNotIn("posible_demanda_censurada", body["preview"]["ventas_historicas"][0])
        self.assertEqual(list(self.directory.iterdir()), [])  # uploads no se persisten

    async def test_positive_credit_and_returned_bonus(self):
        self.tables["ventas_historicas"].loc[1, ["unidades_vendidas", "venta_neta_usd", "unidades_bonificadas"]] = [3, 6, 1]
        response = await self.post()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["preview"]["notas_credito"][0]["unidades_venta_netas"], -3)
        self.assertEqual(body["resumen_procesamiento"]["ventas"]["unidades_bonificadas_devueltas"], 1)
        self.assertEqual(body["resumen_procesamiento"]["ventas"]["unidades_salida_netas"], 8)
        self.assertIn("SIGNO_NC_NORMALIZADO", {w["codigo"] for w in body["advertencias"]})

    async def test_local_and_mixed_modes_preserve_original_files(self):
        originals = {}
        for name, df in self.tables.items():
            content = excel(df, main.SCHEMAS[name]["sheet"])
            path = self.directory / f"{name}.xlsx"
            path.write_bytes(content)
            originals[path] = content
        response = await self.client.post("/api/v1/ingest/validate")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(v["origen"] == "local" for v in response.json()["resumen"].values()))
        response = await self.post({"ventas_historicas": self.tables["ventas_historicas"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["resumen"]["ventas_historicas"]["origen"], "upload")
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    async def test_missing_column(self):
        self.tables["ventas_historicas"] = self.tables["ventas_historicas"].drop(columns="tipo_doc")
        response = await self.post()
        self.assert_error(response, "COLUMNAS_FALTANTES")
        self.assertEqual(response.json()["resumen"]["ventas_historicas"]["filas_leidas"], 2)

    async def test_missing_local_files(self):
        self.assert_error(await self.client.post("/api/v1/ingest/validate"), "ARCHIVO_FALTANTE")

    async def test_negative_invoice(self):
        self.tables["ventas_historicas"].loc[0, "unidades_vendidas"] = -10
        self.assert_error(await self.post(), "FACTURA_NEGATIVA")

    async def test_unknown_document(self):
        self.tables["ventas_historicas"].loc[0, "tipo_doc"] = "DESCONOCIDO"
        self.assert_error(await self.post(), "TIPO_DOCUMENTO_INVALIDO")

    async def test_unknown_sku(self):
        self.tables["ventas_historicas"].loc[0, "sku_id"] = "NO-EXISTE"
        self.assert_error(await self.post(), "SKU_DESCONOCIDO")

    async def test_invalid_numeric_values(self):
        for value, expected in [("texto", "NUMERO_INVALIDO"), ("inf", "NUMERO_INVALIDO"), (1.5, "UNIDADES_NO_ENTERAS")]:
            with self.subTest(value=value):
                tables = fixtures()
                tables["ventas_historicas"]["unidades_vendidas"] = tables["ventas_historicas"]["unidades_vendidas"].astype(object)
                tables["ventas_historicas"].loc[0, "unidades_vendidas"] = value
                self.assert_error(await self.post(tables), expected)

    async def test_missing_stock_is_not_zero(self):
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = None
        self.assert_error(await self.post(), "VALOR_REQUERIDO")

    async def test_negative_stock(self):
        self.tables["inventario_actual"].loc[0, "stock_disponible"] = -1
        self.assert_error(await self.post(), "STOCK_NEGATIVO")

    async def test_dates_invalid_and_ambiguous(self):
        for value in ["2026-02-30", "03/04/2026", 123]:
            with self.subTest(value=value):
                self.tables["ventas_historicas"].loc[0, "fecha_factura"] = value
                self.assert_error(await self.post(), "FECHA_INVALIDA")

    async def test_duplicate_sku(self):
        self.tables["catalogo_sku"] = pd.concat([self.tables["catalogo_sku"]] * 2, ignore_index=True)
        self.tables["catalogo_sku"].loc[1, "nombre_producto"] = "Otro nombre"
        self.assert_error(await self.post(), "SKU_DUPLICADO")

    async def test_duplicate_inventory_key(self):
        self.tables["inventario_actual"] = pd.concat([self.tables["inventario_actual"]] * 2, ignore_index=True)
        self.tables["inventario_actual"].loc[1, "stock_disponible"] = 12
        self.assert_error(await self.post(), "LOTE_DUPLICADO")

    async def test_zero_lot_does_not_imply_zero_sku(self):
        df = pd.concat([self.tables["inventario_actual"]] * 2, ignore_index=True)
        df.loc[1, ["lote", "stock_disponible"]] = ["LOTE-2", 12]
        self.tables["inventario_actual"] = df
        response = await self.post()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["resumen_procesamiento"]["inventario"]
        self.assertEqual(result["filas_stock_cero"], 1)
        self.assertEqual(result["sku_bodega_sin_stock"], 0)

    async def test_transit_requires_metadata(self):
        self.tables["inventario_actual"].loc[0, "stock_en_transito"] = 12
        self.assert_error(await self.post(), "TRANSITO_INCOMPLETO")

    async def test_inventory_mixed_dates(self):
        df = pd.concat([self.tables["inventario_actual"]] * 2, ignore_index=True)
        df.loc[1, "fecha_corte"] = "2026-10-20"
        self.tables["inventario_actual"] = df
        self.assert_error(await self.post(), "CORTES_MEZCLADOS")

    async def test_invalid_workbook_and_sheet(self):
        files = uploads(self.tables)
        files["ventas_historicas"] = ("ventas.xlsx", b"invalid zip", "application/octet-stream")
        self.assert_error(await self.client.post("/api/v1/ingest/validate", files=files), "EXCEL_INVALIDO")
        files["ventas_historicas"] = ("ventas.xlsx", excel(self.tables["ventas_historicas"], "Incorrecta"))
        self.assert_error(await self.client.post("/api/v1/ingest/validate", files=files), "HOJA_FALTANTE")

    async def test_oversized_workbook(self):
        with patch.object(main, "MAX_FILE_BYTES", 10):
            self.assert_error(await self.post(), "ARCHIVO_DEMASIADO_GRANDE", status=413)
        with patch.object(main, "MAX_EXTRACTED_BYTES", 10):
            self.assert_error(await self.post(), "EXCEL_DEMASIADO_GRANDE", status=413)
        with patch.object(main, "MAX_ROWS", 1):
            self.assert_error(await self.post(), "DEMASIADAS_FILAS", status=413)

    async def test_duplicate_headers_after_normalization(self):
        df = self.tables["ventas_historicas"]
        df[" SKU_ID "] = df.sku_id
        self.assert_error(await self.post(), "CABECERA_INVALIDA")

    async def test_bad_ean_warns_without_blocking(self):
        self.tables["catalogo_sku"].loc[0, "ean"] = "7410100000000"
        response = await self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("EAN_INVALIDO", {w["codigo"] for w in response.json()["advertencias"]})

    async def test_preview_and_request_validation(self):
        response = await self.post(params={"preview_limit": 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["preview"]["ventas_historicas"]), 1)
        self.assert_error(await self.post(params={"preview_limit": 0}), "SOLICITUD_INVALIDA")

    async def test_cors_preflight(self):
        response = await self.client.options("/api/v1/ingest/validate", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:3000")


if __name__ == "__main__":
    unittest.main()
