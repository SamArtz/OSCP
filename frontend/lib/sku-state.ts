/** El backend calcula el estado; el cliente lo consume sin repetir las reglas. */
export const healthStates = ["quiebre", "exceso", "optimo", "sin_datos"] as const;
export type HealthState = typeof healthStates[number];
export type HealthCounts = Record<HealthState, number>;
export interface SKUState { sku_id: string; estado_salud: HealthState }

export const healthLabels: Record<HealthState, string> = {
  quiebre: "Quiebre / riesgo", exceso: "En exceso", optimo: "Óptimos", sin_datos: "Sin datos suficientes",
};
export const isCritical = (row: SKUState) => row.estado_salud === "quiebre";

export function validateHealthSummary(rows: SKUState[], summary: HealthCounts): void {
  const seen = new Set<string>();
  const counts: HealthCounts = { quiebre: 0, exceso: 0, optimo: 0, sin_datos: 0 };
  for (const row of rows) {
    if (!row.sku_id || seen.has(row.sku_id) || !healthStates.includes(row.estado_salud)) {
      throw new Error("El servicio devolvió SKU duplicados o estados de salud inválidos. Actualiza FastAPI y recalcula.");
    }
    seen.add(row.sku_id); counts[row.estado_salud] += 1;
  }
  if (!summary || healthStates.some(state => summary[state] !== counts[state])) {
    throw new Error("Los contadores del servicio no coinciden con el estado de sus filas. Recalcula los datos.");
  }
}
