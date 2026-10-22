import type { OCSResponse, OCSRow, Sources } from "./types";

export function sourceForm(sources: Sources) {
  const form = new FormData();
  for (const [name, file] of Object.entries(sources)) if (file) form.append(name, file);
  return form;
}

export function errorMessage(body: unknown, fallback = "No se pudo completar la solicitud."): string {
  if (typeof body !== "object" || body === null || !("errores" in body) || !Array.isArray(body.errores)) return fallback;
  return body.errores.slice(0, 5).map(error => {
    if (!error || typeof error !== "object" || !("mensaje" in error)) return fallback;
    return `${"archivo" in error ? `${error.archivo}: ` : ""}${error.mensaje}${"columnas" in error && Array.isArray(error.columnas) ? ` (${error.columnas.join(", ")})` : ""}`;
  }).join(" · ") || fallback;
}

export function validateResponse(body: unknown): OCSResponse {
  const candidate = body as OCSResponse;
  if (!candidate || candidate.estado !== "exito" || !Array.isArray(candidate.orden_sugerida) || !candidate.parametros || !Array.isArray(candidate.advertencias)) {
    throw new Error("La respuesta del servicio no tiene el formato OCS esperado.");
  }
  if (!/^[a-f0-9]{64}$/.test(candidate.huella_datos || "") || candidate.orden_sugerida.some(row =>
    !row.sku_id || !row.proveedor_id || typeof row.categoria !== "string" || typeof row.marca !== "string" ||
    typeof row.clasificacion_abc !== "string" || !Number.isFinite(row.costo_unitario_usd) ||
    !Number.isInteger(row.unidades_por_caja) || row.unidades_por_caja <= 0
  )) throw new Error("Actualiza FastAPI al Paso 3: faltan los metadatos de catálogo o la versión de datos necesaria para exportar.");
  return candidate;
}

export async function fetchSuggestions(sources: Sources, days: number, signal: AbortSignal) {
  const response = await fetch(`/api/replenishment?ventana_dias=${days}`, { method: "POST", body: sourceForm(sources), signal });
  const body: unknown = await response.json();
  if (!response.ok) throw new Error(errorMessage(body));
  return validateResponse(body);
}

export async function downloadOrder(data: OCSResponse, lines: { row: OCSRow; boxes: number }[], sources: Sources) {
  const form = sourceForm(sources);
  const { ventana_dias, nivel_servicio, peso_estacional, dias_revision } = data.parametros;
  form.append("orden", JSON.stringify({
    fecha_corte: data.fecha_corte, huella_datos: data.huella_datos,
    parametros: { ventana_dias, nivel_servicio, peso_estacional, dias_revision },
    lineas: lines.map(({ row, boxes }) => ({ sku_id: row.sku_id, proveedor_id: row.proveedor_id, cantidad_cajas: boxes })),
  }));
  const response = await fetch("/api/replenishment/export", { method: "POST", body: form });
  if (!response.ok) throw new Error(errorMessage(await response.json()));
  if (!response.headers.get("Content-Type")?.includes("spreadsheetml")) throw new Error("El servicio no devolvió un archivo Excel válido.");
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `OCS_${data.fecha_corte}.xlsx`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
