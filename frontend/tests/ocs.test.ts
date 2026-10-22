import assert from "node:assert/strict";
import { test } from "node:test";
import { boxText, filterRows, isAdjusted, quantity, quantityError, rowKey, selectedOrder } from "../lib/ocs.ts";
import type { OCSRow } from "../lib/types.ts";

const row: OCSRow = {
  proveedor_id: "PROV-1", sku_id: "SKU-1", sku_proveedor: "P-1", nombre_producto: "Néctar de durazno",
  categoria: "Bebidas", marca: "Marca A", clasificacion_abc: "A", costo_unitario_usd: 2,
  estado_sku: "ACTIVO", estado_sugerencia: "CALCULADO", stock_disponible: 0, stock_utilizable: 0,
  stock_en_transito: 12, stock_en_transito_a_tiempo: 0, lead_time_dias: 5,
  pronostico_demanda_lead_time: 30, stock_seguridad: 5, punto_reorden: 35, bajo_punto_reorden: true,
  demanda_no_cubierta_antes_recepcion: 30, unidades_por_caja: 12, moq_cajas: 2,
  cantidad_sugerida_cajas: 3, cantidad_sugerida_unidades: 36, costo_total_usd: 72, prioridad_fefo: [],
};

test("solo acepta cajas enteras, no vacíos, negativos o exponentes", () => {
  for (const value of ["", "-1", "1.5", "2e3", "NaN", "1000001"]) assert.equal(quantity(value), null);
  assert.equal(quantity("0"), 0);
  assert.equal(quantity("6"), 6);
});
test("aplica MOQ, permitiendo cero para omitir", () => {
  assert.ok(quantityError(row, "1"));
  assert.equal(quantityError(row, "0"), null);
  assert.equal(quantityError(row, "2"), null);
});
test("un ajuste cambia unidades y total, preservando sugerencia", () => {
  const edits = { [rowKey(row)]: "5" };
  const order = selectedOrder([row], new Set([rowKey(row)]), edits);
  assert.equal(order.boxes, 5);
  assert.equal(order.units, 60);
  assert.equal(order.total, 120);
  assert.equal(row.cantidad_sugerida_cajas, 3);
  assert.equal(isAdjusted(row, edits), true);
});
test("selección global conserva líneas ocultas por filtros", () => {
  const second = { ...row, proveedor_id: "PROV-2", sku_id: "SKU-2" };
  const rows = [row, second];
  const filtered = filterRows(rows, { supplier: "PROV-1", category: "", brand: "", search: "", view: "todos" }, {}, []);
  assert.equal(filtered.length, 1);
  const order = selectedOrder(rows, new Set(rows.map(rowKey)), {});
  assert.equal(order.lines.length, 2);
  assert.equal(order.total, 144);
});
test("no descarta silenciosamente cantidades inválidas seleccionadas", () => {
  const order = selectedOrder([row], new Set([rowKey(row)]), { [rowKey(row)]: "1" });
  assert.equal(order.invalid.length, 1);
  assert.equal(order.lines.length, 0);
});
test("filtra categoría, marca y búsqueda sin acentos", () => {
  const filters = { supplier: "", category: "Bebidas", brand: "Marca A", search: "nectar", view: "todos" };
  assert.equal(filterRows([row], filters, {}, []).length, 1);
  assert.equal(filterRows([row], { ...filters, brand: "Otra" }, {}, []).length, 0);
});
test("productos descontinuados no son comprables", () => {
  assert.ok(quantityError({ ...row, estado_sku: "DESCONTINUADO" }, "3"));
});
test("restaurar mantiene la sugerencia si no hay edición", () => {
  assert.equal(boxText(row, {}), "3");
  assert.equal(isAdjusted(row, {}), false);
});
test("una compra manual sobre sugerencia cero conserva el costo unitario real", () => {
  const zero = { ...row, cantidad_sugerida_cajas: 0, cantidad_sugerida_unidades: 0, costo_total_usd: 0 };
  const order = selectedOrder([zero], new Set([rowKey(zero)]), { [rowKey(zero)]: "5" });
  assert.equal(order.units, 60);
  assert.equal(order.total, 120);
});
