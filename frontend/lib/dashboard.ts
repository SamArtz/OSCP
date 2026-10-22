import { normalize } from "./ocs.ts";
import { healthStates, type HealthState } from "./sku-state.ts";
export { healthLabels } from "./sku-state.ts";
export type { HealthState } from "./sku-state.ts";

export type ExposureKey = "capital_sobreinventario_usd" | "venta_riesgo_quiebre_usd" | "inventario_riesgo_vencimiento_usd";
export interface DashboardSKU {
  sku_id: string; nombre_producto: string; proveedor_id: string; categoria: string; marca: string; estado_sku: string;
  clase_volumen: string; clase_margen: string | null; margen_estimado_periodo_usd: number | null;
  estado_salud: HealthState; stock_disponible: number | null; stock_utilizable: number | null;
  demanda_diaria_promedio: number | null; cobertura_dias: number | null;
  sin_demanda_reciente: boolean; sin_historial: boolean;
  capital_sobreinventario_usd: number | null; venta_riesgo_quiebre_usd: number | null;
  inventario_riesgo_vencimiento_usd: number; inventario_vencido_usd: number;
}
export interface DashboardResponse {
  estado: "exito"; fecha_corte: string; total_skus: number;
  capital_sobreinventario_usd: number; venta_riesgo_quiebre_usd: number; inventario_riesgo_vencimiento_usd: number; inventario_vencido_usd: number;
  salud_catalogo: Record<HealthState, number>;
  matriz_abc: { volumen: string; margen: string; cantidad: number }[];
  skus_sin_clase_margen: number;
  cobertura_calculo: { skus_sin_estimacion_exceso: number; skus_clase_a_sin_estimacion_quiebre: number };
  parametros: { ventana_dias: number; dias_sobreinventario: number; dias_riesgo_quiebre: number; dias_riesgo_vencimiento: number; cortes_abc_margen: number[] };
  criterios: Record<string, string>;
  advertencias: { codigo: string; mensaje: string; archivo?: string; cantidad?: number }[];
  detalle_skus: DashboardSKU[];
}

export const healthColors: Record<HealthState, string> = { quiebre: "#c77868", exceso: "#cba25d", optimo: "#418d79", sin_datos: "#b3bec5" };
export const exposureLabels: Record<ExposureKey, string> = {
  capital_sobreinventario_usd: "Capital en sobreinventario", venta_riesgo_quiebre_usd: "Venta en riesgo de quiebre", inventario_riesgo_vencimiento_usd: "Inventario próximo a vencer",
};

export function dashboardRows(rows: DashboardSKU[], options: { metric: ExposureKey; onlyExposure: boolean; health: string; volume: string; margin: string; search: string }) {
  const search = normalize(options.search.trim());
  return rows.filter(row =>
    (!options.onlyExposure || (row[options.metric] ?? 0) > 0) &&
    (!options.health || row.estado_salud === options.health) &&
    (!options.volume || row.clase_volumen === options.volume) &&
    (!options.margin || row.clase_margen === options.margin) &&
    (!search || normalize(`${row.sku_id} ${row.nombre_producto} ${row.marca}`).includes(search))
  ).sort((a, b) => (b[options.metric] ?? -1) - (a[options.metric] ?? -1) || a.sku_id.localeCompare(b.sku_id));
}

export function healthShares(health: DashboardResponse["salud_catalogo"]) {
  const total = Object.values(health).reduce((sum, value) => sum + value, 0);
  return healthStates.map(key => ({ key, count: health[key], share: total ? health[key] / total : 0 }));
}
