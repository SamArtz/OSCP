import { test } from "node:test";
import assert from "node:assert/strict";
import { dashboardRows, healthShares } from "../lib/dashboard.ts";
import type { DashboardSKU, ExposureKey } from "../lib/dashboard.ts";

const row: DashboardSKU = {
  sku_id: "SKU-1", nombre_producto: "Néctar", proveedor_id: "P-1", categoria: "Bebidas", marca: "Marca",
  estado_sku: "ACTIVO", clase_volumen: "A", clase_margen: "B", margen_estimado_periodo_usd: 10,
  estado_salud: "exceso", stock_disponible: 100, stock_utilizable: 100,
  demanda_diaria_promedio: 1, cobertura_dias: 100, sin_demanda_reciente: false, sin_historial: false,
  capital_sobreinventario_usd: 10, venta_riesgo_quiebre_usd: 0, inventario_riesgo_vencimiento_usd: 0, inventario_vencido_usd: 0,
};
const options = { metric: "capital_sobreinventario_usd" as ExposureKey, onlyExposure: true, health: "", volume: "", margin: "", search: "" };

test("los estados de salud representan todo el catálogo, incluidos desconocidos", () => {
  const shares = healthShares({ quiebre: 2, exceso: 3, optimo: 4, sin_datos: 1 });
  assert.equal(shares.reduce((sum, item) => sum + item.count, 0), 10);
  assert.ok(Math.abs(shares.reduce((sum, item) => sum + item.share, 0) - 1) < 1e-12);
});
test("un catálogo vacío no produce porcentajes NaN", () => {
  assert.ok(healthShares({ quiebre: 0, exceso: 0, optimo: 0, sin_datos: 0 }).every(item => item.share === 0));
});
test("el detalle de capital incluye solo aportes positivos y ordena por monto", () => {
  const result = dashboardRows([row, { ...row, sku_id: "SKU-2", capital_sobreinventario_usd: 100 }, { ...row, sku_id: "SKU-3", capital_sobreinventario_usd: null }], options);
  assert.deepEqual(result.map(item => item.sku_id), ["SKU-2", "SKU-1"]);
});
test("filtrar salud no oculta productos por tener exposición monetaria cero", () => {
  const unknown = { ...row, estado_salud: "sin_datos" as const, capital_sobreinventario_usd: null };
  assert.equal(dashboardRows([unknown], { ...options, onlyExposure: false, health: "sin_datos" }).length, 1);
});
test("la matriz filtra volumen y margen conjuntamente, con búsqueda sin acentos", () => {
  assert.equal(dashboardRows([row], { ...options, volume: "A", margin: "B", search: "nectar" }).length, 1);
  assert.equal(dashboardRows([row], { ...options, volume: "A", margin: "A" }).length, 0);
});
