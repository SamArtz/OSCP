import assert from "node:assert/strict";
import { test } from "node:test";
import { lineCost, lineCostCents } from "../lib/money.ts";
import { isCritical, validateHealthSummary } from "../lib/sku-state.ts";
import { coverageLabel, filterRows } from "../lib/ocs.ts";
import { validateResponse } from "../lib/api.ts";
import type { OCSResponse, OCSRow } from "../lib/types.ts";

const row: OCSRow = {
  sku_id: "SKU-1029", proveedor_id: "P-1", sku_proveedor: "REF-1029", nombre_producto: "Producto",
  categoria: "Alimentos", marca: "Marca", clasificacion_abc: "A", costo_unitario_usd: 0.73,
  estado_sku: "ACTIVO", estado_sugerencia: "CALCULADO", estado_salud: "optimo", cobertura_dias: 90.004,
  riesgo_quiebre_14_dias: false, auditoria_demanda: null, stock_disponible: 120, stock_utilizable: 120,
  stock_en_transito: 480, stock_en_transito_a_tiempo: 480, lead_time_dias: 15,
  pronostico_demanda_lead_time: 130, stock_seguridad: 5, punto_reorden: 135, bajo_punto_reorden: false,
  demanda_no_cubierta_antes_recepcion: 1, unidades_por_caja: 24, moq_cajas: 10,
  cantidad_sugerida_cajas: 10, cantidad_sugerida_unidades: 240, costo_total_usd: 175.2, prioridad_fefo: [],
};
const counts = { quiebre: 0, exceso: 0, optimo: 1, sin_datos: 0 };
const response: OCSResponse = {
  estado: "exito", fecha_corte: "2026-10-21", huella_datos: "a".repeat(64),
  parametros: { ventana_dias: 60, nivel_servicio: 0.95, peso_estacional: 0.5, dias_revision: 0 },
  advertencias: [{ sku_id: row.sku_id, codigo: "RIESGO_QUIEBRE_ANTES_RECEPCION", mensaje: "Plazo mayor a 14 días" }],
  orden_sugerida: [row], salud_catalogo: counts,
};

test("la salud procede del backend y no del aviso de lead time", () => {
  assert.equal(isCritical(row), false);
  assert.equal(validateResponse(response), response);
  const critical = { ...row, estado_salud: "quiebre" as const };
  assert.equal(isCritical(critical), true);
  const filtered = filterRows([row, { ...critical, sku_id: "SKU-2" }], { supplier: "", category: "", brand: "", search: "", view: "quiebre" }, {});
  assert.deepEqual(filtered.map(item => item.sku_id), ["SKU-2"]);
});
test("se rechazan contadores incoherentes, claves duplicadas y estados desconocidos", () => {
  assert.throws(() => validateHealthSummary([row], { ...counts, quiebre: 12 }));
  assert.throws(() => validateHealthSummary([row, row], { ...counts, optimo: 2 }));
  assert.throws(() => validateHealthSummary([{ ...row, estado_salud: "inventado" } as unknown as OCSRow], counts));
  assert.doesNotThrow(() => validateHealthSummary([row], counts));
});
test("el cliente rechaza costos que no cumplen unidades por costo de catálogo", () => {
  assert.throws(() => validateResponse({ ...response, orden_sugerida: [{ ...row, costo_total_usd: 9999 }] }));
  assert.equal(row.stock_disponible, 120);
  assert.equal(row.stock_en_transito, 480);
});
test("la cobertura muestra un decimal sin cambiar la clasificación exacta", () => {
  assert.equal(coverageLabel(615.298403), "615.3 d");
  assert.equal(coverageLabel(90.004), "90 d");
  assert.equal(coverageLabel(0), "0 d");
  assert.equal(coverageLabel(null), "—");
  assert.equal(isCritical({ ...row, estado_salud: "exceso" }), false);
});
test("los costos usan multiplicación decimal y HALF_UP sin factores ni epsilon", () => {
  for (const [units, cost, expected] of [
    [480, 2.06, 988.8], [240, 0.73, 175.2], [1, 1.005, 1.01],
    [1, 0.005, 0.01], [1, 0.0049999999, 0], [1_000_000, 1e-7, 0.1], [0, 123.456, 0],
  ]) assert.equal(lineCost(units, cost), expected);
  assert.equal(lineCostCents(480, 2.06), 98880);
  assert.throws(() => lineCost(-1, 2));
  assert.throws(() => lineCost(1, NaN));
});
