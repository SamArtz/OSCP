"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine, ArrowRight, ArrowUpRight, Boxes, CalendarDays, Check, CheckCircle2,
  ChevronDown, FileSpreadsheet, Filter, Loader2,
  Package, RefreshCw, RotateCcw, Search, ShieldCheck, SlidersHorizontal,
  TriangleAlert, Upload, X,
} from "lucide-react";
import { downloadOrder, fetchSuggestions } from "@/lib/api";
import { boxText, canBuy, dateLabel, filterRows, isAdjusted, isCritical, number, quantity, rowKey, selectedOrder, usd } from "@/lib/ocs";
import type { Edits, OCSResponse, OCSRow, Sources, View } from "@/lib/types";
import { Dialog } from "./dialog";
import { OrderTable } from "./order-table";
import { SourceUpload } from "./source-upload";
import { WorkspaceShell } from "./workspace-shell";
import { useDataset } from "./dataset-provider";

const PAGE_SIZE = 10;
const emptyFilters = { supplier: "", category: "", brand: "", search: "", view: "todos" as View };

export function ReplenishmentDesk() {
  const [data, setData] = useState<OCSResponse | null>(null);
  const { sources, setSources, windowDays, setWindowDays, sourceLabel } = useDataset();
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [notice, setNotice] = useState("");
  const [edits, setEdits] = useState<Edits>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState(emptyFilters);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<"priority" | "sku-asc" | "sku-desc">("priority");
  const [modal, setModal] = useState<"sources" | "warnings" | "help" | null>(null);
  const [warningSku, setWarningSku] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const rows = useMemo(() => data?.orden_sugerida ?? [], [data]);
  const warnings = useMemo(() => data?.advertencias ?? [], [data]);

  const calculate = useCallback(async (files: Sources, days: number) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setLoading(true); setError(""); setExportError(""); setNotice("");
    try {
      const result = await fetchSuggestions(files, days, current.signal);
      if (current.signal.aborted) return;
      setData(result); setEdits({}); setFilters(emptyFilters); setPage(1);
      setSelected(new Set(result.orden_sugerida.filter(row => canBuy(row) && row.cantidad_sugerida_cajas > 0).map(rowKey)));
    } catch (cause) {
      if (!current.signal.aborted) setError(cause instanceof Error ? cause.message : "No se pudo calcular la orden.");
    } finally {
      if (!current.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => { void calculate(sources, windowDays); return () => controller.current?.abort(); }, [calculate, sources, windowDays]);
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if (event.key === "/" && !(event.target instanceof HTMLElement && event.target.closest("input,textarea,select,[contenteditable]"))) {
        event.preventDefault(); document.getElementById("product-search")?.focus();
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);

  const adjusted = rows.filter(row => isAdjusted(row, edits)).length;
  const critical = rows.filter(row => isCritical(row));
  const order = selectedOrder(rows, selected, edits);
  const originalCost = rows.reduce((total, row) => total + row.costo_total_usd, 0);
  const suppliers = [...new Set(rows.map(row => row.proveedor_id))].sort();
  const categories = [...new Set(rows.map(row => row.categoria))].sort();
  const brands = [...new Set(rows.filter(row => !filters.category || row.categoria === filters.category).map(row => row.marca))].sort();
  const filtered = filterRows(rows, filters, edits).sort((a, b) => {
    if (sort === "sku-asc") return a.sku_id.localeCompare(b.sku_id);
    if (sort === "sku-desc") return b.sku_id.localeCompare(a.sku_id);
    return Number(isCritical(b)) - Number(isCritical(a)) || b.cantidad_sugerida_cajas - a.cantidad_sugerida_cajas || a.sku_id.localeCompare(b.sku_id);
  });
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)));
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const disabled = loading || exporting;
  const canExport = !!data && !disabled && !error && !order.invalid.length && order.lines.length > 0;

  function changeFilter<K extends keyof typeof filters>(key: K, value: (typeof filters)[K]) {
    setFilters(previous => ({ ...previous, [key]: value, ...(key === "category" ? { brand: "" } : {}) })); setPage(1);
  }
  function edit(row: OCSRow, value: string) {
    const key = rowKey(row);
    setEdits(previous => ({ ...previous, [key]: value }));
    setSelected(previous => { const next = new Set(previous); if (quantity(value) === 0) next.delete(key); else next.add(key); return next; });
    setNotice(""); setExportError("");
  }
  function resetRow(row: OCSRow) {
    const key = rowKey(row);
    setEdits(previous => { const next = { ...previous }; delete next[key]; return next; });
    setSelected(previous => { const next = new Set(previous); if (row.cantidad_sugerida_cajas > 0) next.add(key); else next.delete(key); return next; });
  }
  function toggle(key: string) { setSelected(previous => { const next = new Set(previous); if (next.has(key)) next.delete(key); else next.add(key); return next; }); }
  function toggleVisible() {
    const eligible = visible.filter(row => canBuy(row) && (quantity(boxText(row, edits)) ?? 0) > 0).map(rowKey);
    const all = eligible.every(key => selected.has(key));
    setSelected(previous => { const next = new Set(previous); eligible.forEach(key => all ? next.delete(key) : next.add(key)); return next; });
  }
  function recalculate(files = sources, days = windowDays) {
    if (adjusted && !window.confirm("Recalcular descartará las cantidades ajustadas. ¿Deseas continuar?")) return;
    setSources(files); setWindowDays(days); setModal(null);
    if (files === sources && days === windowDays) void calculate(files, days);
  }
  function showWarnings(sku: string | null = null) { setWarningSku(sku); setModal("warnings"); }
  async function exportOrder() {
    if (!canExport || !data) return;
    setExporting(true); setExportError(""); setNotice("");
    try {
      await downloadOrder(data, order.lines.map(row => ({ row, boxes: quantity(boxText(row, edits))! })), sources);
      setNotice(`Archivo descargado: ${order.lines.length} líneas, ${number(order.boxes)} cajas. No se emitió una compra en el ERP.`);
    } catch (cause) { setExportError(cause instanceof Error ? cause.message : "No se pudo descargar la orden."); }
    finally { setExporting(false); }
  }
  const modalWarnings = warningSku ? warnings.filter(warning => warning.sku_id === warningSku) : warnings;
  const selectedSku = rows.find(row => row.sku_id === warningSku);

  return <WorkspaceShell section="replenishment" onHelp={() => setModal("help")}>
      <main>
        <div className="page-heading"><div><div className="page-eyebrow"><span className="eyebrow-line" /> REABASTECIMIENTO INTELIGENTE</div><h1>Mesa de trabajo <span>OCS</span></h1><p>De la demanda a la compra. Revisa, ajusta y confirma tu próximo pedido.</p></div><div className="heading-actions"><button className="button-secondary" disabled={disabled} onClick={() => setModal("sources")}><Upload size={16} /> Cargar archivos</button><button className="button-primary" onClick={exportOrder} disabled={!canExport}>{exporting ? <Loader2 size={16} className="animate-spin" /> : <ArrowDownToLine size={16} />} Descargar Orden de Compra (.xlsx)</button></div></div>

        <div className="context-row"><div className="context-item"><CalendarDays size={14} /><span>Corte de inventario</span><strong>{data ? dateLabel(data.fecha_corte) : "Pendiente"}</strong></div><span className="context-separator" /><div className="context-item"><span className={`connection-dot ${data && !error ? "online" : ""}`} />{loading ? "Calculando sugerencias…" : error ? "Requiere atención" : data ? "Datos validados" : "Sin datos"}</div><span className="context-item">{sourceLabel}</span><div className="model-label"><span className="model-dot" /> Baseline + estacionalidad semanal</div></div>

        {error && <div className="error-banner" role="alert"><TriangleAlert size={20} /><div><strong>No pudimos actualizar las sugerencias</strong><p>{error}</p>{data && <p>La tabla conserva el cálculo anterior. La exportación está deshabilitada hasta actualizarlo.</p>}</div><button className="button-secondary" onClick={() => recalculate()}>Reintentar</button></div>}
        {exportError && <div className="error-banner" role="alert"><TriangleAlert size={20} /><div><strong>No se pudo descargar la orden</strong><p>{exportError}</p></div><button className="icon-button" aria-label="Cerrar error de exportación" onClick={() => setExportError("")}><X size={18} /></button></div>}
        {notice && <div className="success-banner" role="status"><CheckCircle2 size={18} />{notice}<button className="icon-button" aria-label="Cerrar aviso" onClick={() => setNotice("")}><X size={17} /></button></div>}

        <section className={`metric-grid ${loading ? "metrics-loading" : ""}`} aria-label="Resumen de compra">
          <Metric label="COMPRA CONFIRMADA" value={data ? usd(order.total) : "—"} icon={<span className="money-symbol">$</span>} foot={data ? `Sugerencia inicial: ${usd(originalCost)}` : "Pendiente de cálculo"} accent />
          <Metric label="SKU A REABASTECER" value={data ? number(order.lines.length) : "—"} icon={<Package size={19} />} foot={data ? `De ${rows.length} productos analizados` : "Catálogo de productos"} />
          <Metric label="CAJAS CONFIRMADAS" value={data ? number(order.boxes) : "—"} icon={<Boxes size={19} />} foot={data ? `${number(order.units)} unidades físicas` : "Respeta múltiplos de caja"} />
          <Metric label="RIESGO DE QUIEBRE" value={data ? number(critical.length) : "—"} icon={<TriangleAlert size={19} />} foot="Actual o proyectado a 14 días" danger={critical.length > 0} />
        </section>

        {!!data && <div className={`attention-strip ${critical.length > 0 ? "has-alerts" : ""}`}><div className="attention-icon">{critical.length > 0 ? <TriangleAlert size={18} /> : <ShieldCheck size={18} />}</div><p>{critical.length > 0 ? <><strong>{critical.length} SKU en quiebre o riesgo a 14 días.</strong><span> Mismo criterio que el tablero. Revisa también los avisos de urgencia durante el lead time.</span></> : <><strong>Revisa las restricciones antes de confirmar.</strong><span> Las cantidades sugeridas respetan el MOQ y los múltiplos de caja.</span></>}</p><button onClick={() => showWarnings()}>Revisar avisos <ArrowUpRight size={15} /></button></div>}

        <section className="workbench" aria-label="Mesa de trabajo OCS">
          <div className="workbench-heading"><div><h2>Sugerencias de compra <span className="count-badge">{rows.length}</span></h2><p>La sugerencia es tu punto de partida. Tú confirmas la cantidad final.</p></div><div className="workbench-controls"><label className="window-select"><CalendarDays size={14} /><select aria-label="Ventana histórica" value={windowDays} disabled={disabled} onChange={event => recalculate(sources, Number(event.target.value))}><option value={60}>Últimos 60 días</option><option value={30}>Últimos 30 días</option></select><ChevronDown size={12} /></label><button className="icon-button refresh-button" title="Recalcular con los archivos actuales" aria-label="Recalcular sugerencias" disabled={disabled} onClick={() => recalculate()}><RefreshCw size={16} className={loading ? "animate-spin" : ""} /></button></div></div>

          <div className="filters-row"><div className="search-box"><Search size={16} /><input id="product-search" aria-label="Buscar SKU, descripción o marca" placeholder="Buscar SKU, producto o marca…" value={filters.search} onChange={event => changeFilter("search", event.target.value)} /><kbd>/</kbd></div><FilterSelect label="Proveedor" value={filters.supplier} values={suppliers} onChange={value => changeFilter("supplier", value)} /><FilterSelect label="Categoría" value={filters.category} values={categories} onChange={value => changeFilter("category", value)} /><FilterSelect label="Marca" value={filters.brand} values={brands} onChange={value => changeFilter("brand", value)} />{Object.values(filters).some(value => value && value !== "todos") && <button className="clear-filters" onClick={() => { setFilters(emptyFilters); setPage(1); }}>Limpiar <X size={13} /></button>}</div>
          <div className="table-toolbar"><div className="view-tabs" role="group" aria-label="Vista de productos">{([
            ["todos", "Todos", rows.length], ["quiebre", "Riesgo de quiebre", critical.length], ["compra", "Con compra", rows.filter(row => (quantity(boxText(row, edits)) ?? 0) > 0).length], ["ajustes", "Ajustados", adjusted],
          ] as const).map(([value, label, count]) => <button key={value} className={filters.view === value ? "active" : ""} aria-pressed={filters.view === value} onClick={() => changeFilter("view", value)}>{label}<span>{count}</span></button>)}</div><div className="table-toolbar-right">{adjusted > 0 && <button className="reset-all" disabled={disabled} onClick={() => { if (window.confirm("¿Restaurar todas las sugerencias originales?")) { setEdits({}); setSelected(new Set(rows.filter(row => canBuy(row) && row.cantidad_sugerida_cajas > 0).map(rowKey))); } }}><RotateCcw size={13} />Restaurar</button>}<span title="Las cantidades son sugerencias, no órdenes emitidas"><SlidersHorizontal size={13} /> Revisión manual</span></div></div>

          {loading && !data ? <div className="loading-state" role="status"><Loader2 size={28} className="animate-spin text-accent" /><h3>Preparando tu mesa de compras</h3><p>Validando archivos y calculando demanda, cobertura y restricciones.</p><div className="skeleton-row" /><div className="skeleton-row" /><div className="skeleton-row" /></div> : !data ? <div className="empty-state"><FileSpreadsheet size={34} /><h3>Tu próxima compra empieza con tus datos</h3><p>Carga ventas, catálogo e inventario para generar las primeras sugerencias.</p><button className="button-primary" onClick={() => setModal("sources")}><Upload size={16} />Cargar mis archivos</button></div> : <div className={loading ? "table-updating" : ""} aria-busy={loading}><OrderTable rows={visible} warnings={warnings} edits={edits} selected={selected} disabled={disabled} page={currentPage} total={filtered.length} pageSize={PAGE_SIZE} onPage={setPage} onEdit={edit} onSelect={toggle} onSelectVisible={toggleVisible} onReset={resetRow} onWarnings={showWarnings} onSort={() => setSort(previous => previous === "sku-asc" ? "sku-desc" : "sku-asc")} /></div>}
        </section>

        <div className="review-note"><ShieldCheck size={15} /><p>La compra queda bajo tu revisión. El modelo no corrige demanda perdida por rupturas ni emite órdenes automáticamente.</p><button onClick={() => setModal("help")}>Cómo funciona <ArrowRight size={12} /></button></div>
        <footer className="purchase-summary"><div className="summary-left"><span className="selection-icon"><Check size={17} /></span><div><strong>{order.lines.length} líneas seleccionadas <span>· {number(order.boxes)} cajas</span></strong><p>La selección incluye líneas ocultas por filtros y paginación.</p></div></div><div className="summary-right"><div className="summary-total"><span>Total de mercancía · sin IVA ni flete</span><strong>{usd(order.total)}</strong></div><button className="button-primary" onClick={exportOrder} disabled={!canExport}>{exporting ? <Loader2 size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />} Descargar .xlsx <ArrowRight size={15} /></button></div>{order.invalid.length > 0 && <p className="summary-error" role="alert">Corrige las cantidades de {order.invalid.length} líneas seleccionadas antes de descargar.</p>}</footer>
        <p className="page-footnote">ABASTO · PLANIFICACIÓN DE COMPRAS <span>XLSX estándar · Importes en USD</span></p>
        <span className="sr-only" aria-live="polite">{loading ? "Calculando sugerencias" : data ? `${rows.length} productos cargados. ${order.lines.length} líneas seleccionadas.` : "Sin datos cargados"}</span>
      </main>

    {modal === "sources" && <Dialog title="Actualizar fuentes de datos" onClose={() => setModal(null)}><SourceUpload current={sources} onCalculate={files => recalculate(files)} /></Dialog>}
    {modal === "help" && <Dialog title="De la sugerencia a tu orden" onClose={() => setModal(null)}><div className="help-steps"><HelpStep number="01" title="Valida tus datos">Carga tus tres Excel o utiliza los archivos locales del servicio. El corte del inventario determina la fecha del cálculo.</HelpStep><HelpStep number="02" title="Revisa la cobertura">El pronóstico usa ventas facturadas y bonos. El ROP suma demanda durante el plazo y stock de seguridad al 95% de servicio.</HelpStep><HelpStep number="03" title="Confirma cantidades">Edita cajas completas o ingresa cero para omitir. El MOQ sigue vigente; los SKU descontinuados o sin datos suficientes requieren revisión y no se exportan.</HelpStep><HelpStep number="04" title="Descarga tu selección">Selecciona las líneas que deseas comprar. El XLSX estándar contiene Orden_Compra, Auditoria y Parametros. No es una integración certificada con un ERP.</HelpStep></div><div className="source-note"><ShieldCheck size={18} /><p>Los cambios de cantidad son temporales y se descartan al recargar la página o recalcular. Descarga tu orden para conservarlos.</p></div></Dialog>}
    {modal === "warnings" && <Dialog title={warningSku ? `Detalle de ${warningSku}` : "Centro de alertas"} onClose={() => setModal(null)}><p className="dialog-description">{selectedSku ? selectedSku.nombre_producto : "Señales del cálculo y calidad de datos. Las alertas no se ocultan al filtrar la tabla."}</p><div className="warning-list">{modalWarnings.length ? modalWarnings.map((warning, index) => <article className={`warning-item ${warning.codigo.includes("QUIEBRE") ? "critical-warning" : ""}`} key={index}><TriangleAlert size={18} /><div><span className="warning-label">{warning.sku_id || warning.archivo || "Cálculo general"}</span><h3>{warning.codigo.toLowerCase().replaceAll("_", " ")}</h3><p>{warning.mensaje}{warning.cantidad ? ` (${warning.cantidad} registros)` : ""}</p></div></article>) : <p className="dialog-description">No hay avisos específicos para este SKU.</p>}</div>{selectedSku && <div className="fefo-section"><h3>Prioridad de rotación FEFO</h3>{selectedSku.prioridad_fefo.map((lot, index) => <div className="fefo-lot" key={`${lot.bodega_id}-${lot.lote}`}><span>{index + 1}</span><div><strong>{lot.lote}</strong><p>{lot.bodega_id} · Vence {dateLabel(lot.fecha_vencimiento)}</p></div><b className={lot.vencido_al_corte ? "text-danger" : ""}>{lot.vencido_al_corte ? "Vencido" : `${number(lot.stock_disponible)} uds.`}</b></div>)}</div>}</Dialog>}
  </WorkspaceShell>;
}

function Metric({ label, value, foot, icon, accent, danger }: { label: string; value: string; foot: string; icon: React.ReactNode; accent?: boolean; danger?: boolean }) {
  return <article className={`metric-card ${accent ? "metric-accent" : ""} ${danger ? "metric-danger" : ""}`}><div className="metric-label">{label}<span className="metric-icon">{icon}</span></div><div className="metric-value">{value}</div><p>{foot}{accent && <ArrowUpRight size={13} />}</p></article>;
}
function FilterSelect({ label, value, values, onChange }: { label: string; value: string; values: string[]; onChange: (value: string) => void }) {
  return <div className="filter-select"><Filter size={13} /><select aria-label={`Filtrar por ${label.toLowerCase()}`} value={value} onChange={event => onChange(event.target.value)}><option value="">{label}: todos</option>{values.map(item => <option key={item} value={item}>{item}</option>)}</select><ChevronDown size={12} /></div>;
}
function HelpStep({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return <div className="help-step"><span>{number}</span><div><h3>{title}</h3><p>{children}</p></div></div>;
}
