import type { Edits, OCSRow } from "./types.ts";
import { isCritical } from "./sku-state.ts";
import { lineCostCents } from "./money.ts";
export { isCritical } from "./sku-state.ts";

export const usd = (value: number) => new Intl.NumberFormat("es-SV", { style: "currency", currency: "USD" }).format(value);
export const number = (value: number | null, digits = 0) => value === null ? "—" : new Intl.NumberFormat("es-SV", { maximumFractionDigits: digits }).format(value);
export const coverageLabel = (value: number | null) => value === null ? "—" : `${number(value, 1)} d`;
export const dateLabel = (value: string) => new Intl.DateTimeFormat("es-SV", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
export const rowKey = (row: Pick<OCSRow, "proveedor_id" | "sku_id">) => JSON.stringify([row.proveedor_id, row.sku_id]);
export const canBuy = (row: OCSRow) => row.estado_sugerencia === "CALCULADO" && row.estado_sku !== "DESCONTINUADO";
export const boxText = (row: OCSRow, edits: Edits) => edits[rowKey(row)] ?? String(row.cantidad_sugerida_cajas);
export function quantity(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed <= 1_000_000 ? parsed : null;
}
export function quantityError(row: OCSRow, value: string): string | null {
  const parsed = quantity(value);
  if (parsed === null) return "Ingresa un entero entre 0 y 1.000.000.";
  if (parsed > 0 && parsed < row.moq_cajas) return `Mínimo ${row.moq_cajas} cajas, o 0 para omitir.`;
  if (parsed > 0 && !canBuy(row)) return "Este SKU requiere revisión antes de comprar.";
  return null;
}
export const isAdjusted = (row: OCSRow, edits: Edits) => boxText(row, edits) !== String(row.cantidad_sugerida_cajas);
export const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
export function filterRows(rows: OCSRow[], filters: { supplier: string; category: string; brand: string; search: string; view: string }, edits: Edits) {
  const search = normalize(filters.search.trim());
  return rows.filter(row =>
    (!filters.supplier || row.proveedor_id === filters.supplier) &&
    (!filters.category || row.categoria === filters.category) &&
    (!filters.brand || row.marca === filters.brand) &&
    (!search || normalize(`${row.sku_id} ${row.nombre_producto} ${row.marca}`).includes(search)) &&
    (filters.view !== "quiebre" || isCritical(row)) &&
    (filters.view !== "compra" || (quantity(boxText(row, edits)) ?? 0) > 0) &&
    (filters.view !== "ajustes" || isAdjusted(row, edits))
  );
}
/** La selección es global y no se pierde al filtrar o paginar. */
export function selectedOrder(rows: OCSRow[], selected: Set<string>, edits: Edits) {
  const selectedRows = rows.filter(row => selected.has(rowKey(row)));
  const invalid = selectedRows.filter(row => quantityError(row, boxText(row, edits)));
  const lines = selectedRows.filter(row => !quantityError(row, boxText(row, edits)) && (quantity(boxText(row, edits)) ?? 0) > 0);
  const boxes = lines.reduce((sum, row) => sum + quantity(boxText(row, edits))!, 0);
  const units = lines.reduce((sum, row) => sum + quantity(boxText(row, edits))! * row.unidades_por_caja, 0);
  const cents = lines.reduce((sum, row) => sum + lineCostCents(quantity(boxText(row, edits))! * row.unidades_por_caja, row.costo_unitario_usd), 0);
  return { lines, invalid, boxes, units, total: cents / 100 };
}
