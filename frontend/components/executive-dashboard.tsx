"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Banknote, CalendarDays, ChevronDown, CircleHelp, Clock3, Info, Loader2, RefreshCw, Search, ShieldCheck, TriangleAlert, Upload, X } from "lucide-react";
import { Dialog } from "./dialog";
import { SourceUpload } from "./source-upload";
import { WorkspaceShell } from "./workspace-shell";
import { CatalogHealth } from "./catalog-health";
import { ABCMatrix } from "./abc-matrix";
import { errorMessage, sourceForm } from "@/lib/api";
import { dashboardRows, exposureLabels, healthLabels } from "@/lib/dashboard";
import type { DashboardResponse, ExposureKey, HealthState } from "@/lib/dashboard";
import { dateLabel, number, usd } from "@/lib/ocs";
import type { Sources } from "@/lib/types";

const metricKeys: ExposureKey[] = ["capital_sobreinventario_usd", "venta_riesgo_quiebre_usd", "inventario_riesgo_vencimiento_usd"];
const subtitles = ["Excedente sobre 90 días · a costo", "Clase A · próximos 14 días · a lista", "Lotes con menos de 120 días · a costo"];
const icons = [<Banknote size={22} key="capital" />, <TriangleAlert size={22} key="risk" />, <Clock3 size={22} key="expiry" />];

export function ExecutiveDashboard() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [sources, setSources] = useState<Sources>({});
  const [windowDays, setWindowDays] = useState(60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<"sources" | "criteria" | null>(null);
  const [metric, setMetric] = useState<ExposureKey>(metricKeys[0]);
  const [onlyExposure, setOnlyExposure] = useState(true);
  const [health, setHealth] = useState("");
  const [matrix, setMatrix] = useState("");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(10);
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async (files: Sources, days: number) => {
    controller.current?.abort();
    const current = new AbortController(); controller.current = current;
    setLoading(true); setError("");
    try {
      const uploaded = Object.values(files).some(Boolean);
      const response = await fetch(`/api/dashboard?ventana_dias=${days}`, {
        method: uploaded ? "POST" : "GET", ...(uploaded ? { body: sourceForm(files) } : {}), signal: current.signal, cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(body, "El servicio no pudo calcular los indicadores. Comprueba FastAPI y vuelve a intentar."));
      if (!body || body.estado !== "exito" || !Array.isArray(body.detalle_skus) || !Array.isArray(body.matriz_abc) || !body.salud_catalogo || metricKeys.some(key => !Number.isFinite(body[key]))) throw new Error("La respuesta no contiene los indicadores del Paso 4. Actualiza también el backend.");
      if (current.signal.aborted) return;
      setData(body); setHealth(""); setMatrix(""); setSearch(""); setLimit(10);
    } catch (cause) {
      if (!current.signal.aborted) setError(cause instanceof Error ? cause.message : "No se pudo actualizar el tablero.");
    } finally { if (!current.signal.aborted) setLoading(false); }
  }, []);
  useEffect(() => { void load({}, 60); return () => controller.current?.abort(); }, [load]);
  const rows = useMemo(() => data?.detalle_skus ?? [], [data]);
  const filtered = useMemo(() => dashboardRows(rows, { metric, onlyExposure, health, volume: matrix[0] || "", margin: matrix[1] || "", search }), [rows, metric, onlyExposure, health, matrix, search]);
  function selectMetric(key: ExposureKey) { setMetric(key); setOnlyExposure(true); setHealth(""); setMatrix(""); setSearch(""); setLimit(10); }
  function selectHealth(state: HealthState) { setHealth(previous => previous === state ? "" : state); setOnlyExposure(false); setLimit(10); }
  function selectMatrix(volume: string, margin: string) { setMatrix(previous => previous === volume + margin ? "" : volume + margin); setOnlyExposure(false); setLimit(10); }
  function showAll() { setOnlyExposure(false); setHealth(""); setMatrix(""); setSearch(""); setLimit(10); }
  const pending = data ? data.cobertura_calculo.skus_sin_estimacion_exceso + data.cobertura_calculo.skus_clase_a_sin_estimacion_quiebre : 0;

  return <WorkspaceShell section="dashboard" onHelp={() => setModal("criteria")}>
    <main className="executive-dashboard">
      <div className="page-heading"><div><div className="page-eyebrow"><span className="eyebrow-line" /> VISIÓN EJECUTIVA</div><h1>Capital <span>y riesgo</span></h1><p>Visibilidad financiera del inventario, con prioridades para actuar.</p></div><div className="heading-actions"><button className="button-secondary" disabled={loading} onClick={() => setModal("sources")}><Upload size={16} /> Cargar archivos</button><Link className="button-primary" href="/replenishment">Abrir mesa OCS <ArrowRight size={16} /></Link></div></div>
      <div className="context-row"><div className="context-item"><CalendarDays size={14} /><span>Corte de inventario</span><strong>{data ? dateLabel(data.fecha_corte) : "Pendiente"}</strong></div><span className="context-separator" /><div className="context-item"><span className={`connection-dot ${data && !error ? "online" : ""}`} />{loading ? "Calculando indicadores…" : error ? "Actualización pendiente" : "Datos validados"}</div><div className="dashboard-context-actions"><label className="window-select"><select aria-label="Ventana del tablero" value={windowDays} disabled={loading} onChange={event => { const days = Number(event.target.value); setWindowDays(days); void load(sources, days); }}><option value={60}>Últimos 60 días</option><option value={30}>Últimos 30 días</option></select><ChevronDown size={12} /></label><button className="icon-button refresh-button" disabled={loading} aria-label="Actualizar indicadores" onClick={() => void load(sources, windowDays)}><RefreshCw size={15} className={loading ? "animate-spin" : ""} /></button></div></div>
      {error && <div className="error-banner" role="alert"><TriangleAlert size={20} /><div><strong>No pudimos actualizar el tablero</strong><p>{error}</p>{data && <p>Los valores visibles corresponden al cálculo anterior; revisa el corte antes de usarlos.</p>}</div><button className="button-secondary" onClick={() => void load(sources, windowDays)}>Reintentar</button></div>}

      <section className={`executive-kpis ${loading ? "metrics-loading" : ""}`} aria-label="Indicadores ejecutivos">{metricKeys.map((key, index) => <button key={key} className={`executive-kpi executive-kpi-${index} ${onlyExposure && metric === key ? "chosen" : ""}`} aria-pressed={onlyExposure && metric === key} disabled={!data || loading} onClick={() => selectMetric(key)}><div className="executive-kpi-top"><span>{exposureLabels[key]}</span><div>{icons[index]}</div></div><strong className="executive-kpi-value">{data ? usd(data[key]) : "—"}</strong><p>{subtitles[index]}</p><div className="executive-kpi-bottom"><span>{data ? `${rows.filter(row => (row[key] ?? 0) > 0).length} SKU con exposición` : "Pendiente de cálculo"}</span><ArrowUpRight size={16} /></div></button>)}</section>

      <div className="executive-criteria-strip"><Info size={15} /><p>Inventario valorado a costo actual; venta en riesgo a precio de lista. Los indicadores pueden superponerse.</p><button onClick={() => setModal("criteria")}>Ver criterios <CircleHelp size={13} /></button></div>
      {pending > 0 && <div className="attention-strip has-alerts"><TriangleAlert size={18} /><p><strong>Estimaciones parciales.</strong> Hay SKU sin historial o inventario suficiente para calcular cobertura o venta Clase A en riesgo. No se consideran óptimos.</p></div>}
      {loading && !data ? <section className="executive-panel loading-state" role="status"><Loader2 size={28} className="animate-spin text-accent" /><h3>Preparando la visión ejecutiva</h3><p>Calculando cobertura, exposición financiera y contribución del catálogo.</p><div className="skeleton-row" /><div className="skeleton-row" /></section> : !data ? <section className="executive-panel empty-state"><Banknote size={34} /><h3>El capital se entiende mejor con datos</h3><p>Carga ventas, catálogo e inventario para calcular los indicadores del tablero.</p><button className="button-primary" onClick={() => setModal("sources")}><Upload size={15} /> Cargar mis archivos</button></section> : <div aria-busy={loading} className={loading ? "dashboard-updating" : ""}>
        <div className="executive-overview"><CatalogHealth data={data} selected={health} onSelect={selectHealth} /><ABCMatrix data={data} selected={matrix} onSelect={selectMatrix} /></div>
        <section className="executive-panel priorities-panel" aria-labelledby="priorities-heading">
          <div className="executive-panel-heading"><div><p className="eyebrow">DEL INDICADOR A LA DECISIÓN</p><h2 id="priorities-heading">{onlyExposure ? "Dónde actuar primero" : "Detalle del catálogo"} <span className="count-badge">{filtered.length} SKU</span></h2></div><button className="executive-text-button" onClick={showAll}>Ver catálogo completo <ArrowRight size={13} /></button></div>
          <div className="priorities-toolbar"><div className="view-tabs">{metricKeys.map((key, index) => <button key={key} aria-pressed={onlyExposure && metric === key} className={onlyExposure && metric === key ? "active" : ""} onClick={() => selectMetric(key)}>{["Sobreinventario", "Venta en riesgo", "Vencimiento"][index]}</button>)}</div><div className="search-box"><Search size={14} /><input aria-label="Buscar en el detalle del tablero" placeholder="Buscar SKU o producto…" value={search} onChange={event => { setSearch(event.target.value); setLimit(10); }} /></div></div>
          {(health || matrix) && <div className="executive-active-filters">{health && <span>{healthLabels[health as HealthState]}<button aria-label="Quitar filtro de salud" onClick={() => setHealth("")}><X size={12} /></button></span>}{matrix && <span>Volumen {matrix[0]} · Margen {matrix[1]}<button aria-label="Quitar filtro ABC" onClick={() => setMatrix("")}><X size={12} /></button></span>}</div>}
          <div className="executive-detail-scroll" role="region" tabIndex={0} aria-label="Detalle de exposición por SKU"><table className="executive-detail-table"><caption className="sr-only">Exposición por producto, cobertura y salud del catálogo. Valores en dólares de Estados Unidos.</caption><thead><tr><th>SKU / Producto</th><th>Vol. / Margen</th><th className="numeric">Stock útil</th><th className="numeric">Cobertura</th><th>Salud</th><th className="numeric">Excedente<br />a costo</th><th className="numeric">Venta en riesgo<br />14 días · Clase A</th><th className="numeric">Vencimiento<br />a costo</th></tr></thead><tbody>{filtered.slice(0, limit).map(row => <tr key={row.sku_id}><td><strong className="sku-code">{row.sku_id}</strong><span className="dashboard-product-name">{row.nombre_producto}</span><span className="cell-meta">{row.marca} · {row.proveedor_id}{row.estado_sku === "DESCONTINUADO" ? " · Descontinuado" : ""}</span></td><td><span className="matrix-class-label">{row.clase_volumen} <span>/</span> {row.clase_margen ?? "—"}</span></td><td className="numeric">{number(row.stock_utilizable)}</td><td className="numeric">{row.sin_historial ? "Sin historial" : row.sin_demanda_reciente ? "Sin rotación" : row.cobertura_dias === null ? "—" : `${number(row.cobertura_dias, 1)} d`}</td><td><span className={`health-state-pill health-state-${row.estado_salud}`}>{healthLabels[row.estado_salud]}</span></td><td className={`numeric ${row.capital_sobreinventario_usd ? "exposure-positive" : ""}`}>{row.capital_sobreinventario_usd === null ? "—" : usd(row.capital_sobreinventario_usd)}</td><td className={`numeric ${row.venta_riesgo_quiebre_usd ? "exposure-risk" : ""}`}>{row.venta_riesgo_quiebre_usd === null ? "—" : usd(row.venta_riesgo_quiebre_usd)}</td><td className="numeric">{usd(row.inventario_riesgo_vencimiento_usd)}</td></tr>)}</tbody></table>{filtered.length === 0 && <div className="empty-state"><ShieldCheck size={28} /><h3>Sin productos para esta selección</h3><p>{onlyExposure ? "No se identificó exposición en este indicador con los criterios del corte." : "Prueba otra combinación de salud, ABC o búsqueda."}</p><button className="executive-text-button" onClick={showAll}>Ver catálogo completo</button></div>}</div>
          <div className="table-footer"><span>Mostrando {Math.min(limit, filtered.length)} de {filtered.length} SKU · Montos en USD</span>{filtered.length > limit && <button className="executive-text-button" onClick={() => setLimit(filtered.length)}>Ver todos los productos <ChevronDown size={13} /></button>}</div>
        </section>
        <div className="review-note"><ShieldCheck size={15} /><p>Proyecciones para priorizar decisiones. El margen es una estimación a costo actual; la exposición no equivale a pérdida confirmada.</p><button onClick={() => setModal("criteria")}>Metodología <ArrowRight size={12} /></button></div>
      </div>}
      <p className="page-footnote">ABASTO · CAPITAL Y RIESGO <span>Inventario al corte · Moneda USD</span></p>
      <span className="sr-only" aria-live="polite">{loading ? "Calculando tablero" : data ? `${data.total_skus} productos analizados. ${data.salud_catalogo.quiebre} en quiebre o riesgo a 14 días.` : "Sin datos del tablero"}</span>
    </main>
    {modal === "sources" && <Dialog title="Fuentes del tablero ejecutivo" onClose={() => setModal(null)}><SourceUpload current={sources} actionLabel="Actualizar tablero" onCalculate={files => { setSources(files); setModal(null); void load(files, windowDays); }} /></Dialog>}
    {modal === "criteria" && <Dialog title="Cómo leer capital y riesgo" onClose={() => setModal(null)}><p className="dialog-description">Los tres indicadores responden preguntas diferentes: capital inmovilizado, venta sin cobertura y exposición de lotes. No deben sumarse como una pérdida total.</p><div className="dashboard-methodology">{data ? Object.entries(data.criterios).map(([key, value]) => <article key={key}><h3>{({ capital: "Capital en sobreinventario", quiebre: "Venta en riesgo", vencimiento: "Exposición a vencimiento", salud: "Salud del catálogo", abc: "Matriz ABC 3 × 3", margen: "Margen bruto estimado", alcance: "Alcance del cálculo" } as Record<string, string>)[key] || key}</h3><p>{value}</p></article>) : <p>Se necesitan ventas históricas, catálogo e inventario. El capital excedente se calcula sobre 90 días; el riesgo comercial, sobre 14 días; el vencimiento, sobre lotes con menos de 120 días remanentes.</p>}</div>{data && data.advertencias.length > 0 && <div className="dashboard-methodology"><h3>Avisos de datos</h3>{data.advertencias.map((warning, index) => <p key={index}>{warning.mensaje}{warning.cantidad ? ` (${warning.cantidad} registros)` : ""}</p>)}</div>}</Dialog>}
  </WorkspaceShell>;
}
