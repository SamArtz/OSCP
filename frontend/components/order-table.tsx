"use client";

import { ChevronLeft, ChevronRight, Info, RotateCcw, AlertTriangle, ArrowUpDown } from "lucide-react";
import { boxText, canBuy, isAdjusted, isCritical, number, quantity, quantityError, rowKey, usd } from "@/lib/ocs";
import type { Edits, OCSRow, Warning } from "@/lib/types";

type Props = {
  rows: OCSRow[]; warnings: Warning[]; edits: Edits; selected: Set<string>; disabled: boolean;
  page: number; total: number; pageSize: number;
  onPage: (page: number) => void; onEdit: (row: OCSRow, text: string) => void;
  onSelect: (key: string) => void; onSelectVisible: () => void; onReset: (row: OCSRow) => void;
  onWarnings: (sku: string) => void; onSort: () => void;
};

export function OrderTable(props: Props) {
  const { rows, warnings, edits, selected, disabled, page, total, pageSize, onPage, onEdit, onSelect, onSelectVisible, onReset, onWarnings, onSort } = props;
  const selectable = rows.filter(row => canBuy(row) && (quantity(boxText(row, edits)) ?? 0) > 0);
  const allVisible = selectable.length > 0 && selectable.every(row => selected.has(rowKey(row)));
  return <>
    <p className="mobile-scroll-note">Desliza la tabla para revisar existencias y confirmar cajas →</p>
    <div className="table-scroll" tabIndex={0} role="region" aria-label="Tabla de sugerencias de compra; desplazamiento horizontal disponible">
      <table className="order-table">
        <caption className="sr-only">Sugerencias por SKU. Las existencias y pronósticos están en unidades; las cantidades editables, en cajas completas.</caption>
        <thead><tr>
          <th className="selection-cell"><input aria-label="Seleccionar líneas comprables de esta página" type="checkbox" checked={allVisible} ref={node => { if (node) node.indeterminate = !allVisible && selectable.some(row => selected.has(rowKey(row))); }} disabled={disabled || selectable.length === 0} onChange={onSelectVisible} /></th>
          <th><button className="table-sort" onClick={onSort}>SKU <ArrowUpDown size={11} /></button></th><th>Descripción / Señal</th><th>ABC</th>
          <th className="numeric">Stock<br />físico</th><th className="numeric">Tránsito</th><th className="numeric">Pronóstico<br />lead time</th>
          <th className="numeric">Stock de<br />seguridad</th><th className="numeric">Punto de<br />reorden</th><th className="numeric suggestion-head">Sugerencia IA<br /><span>Cajas / unidades</span></th><th className="confirmed-head">Compra confirmada<br /><span>Cajas completas</span></th>
        </tr></thead>
        <tbody>{rows.map(row => {
          const key = rowKey(row), value = boxText(row, edits), parsed = quantity(value), error = quantityError(row, value);
          const adjusted = isAdjusted(row, edits), buyable = canBuy(row), critical = isCritical(row, warnings);
          const rowWarnings = warnings.filter(warning => warning.sku_id === row.sku_id);
          const discontinued = row.estado_sku === "DESCONTINUADO";
          return <tr key={key} className={`${selected.has(key) ? "selected-row" : ""} ${discontinued ? "inactive-row" : ""}`}>
            <td className="selection-cell"><input type="checkbox" aria-label={`Seleccionar ${row.sku_id}`} checked={selected.has(key)} disabled={disabled || !buyable || parsed === 0} onChange={() => onSelect(key)} /></td>
            <td className="sku-cell"><span className="sku-code">{row.sku_id}</span><span className="cell-meta">{row.proveedor_id}</span></td>
            <td className="description-cell"><span className="product-name">{row.nombre_producto}</span><span className="cell-meta">{row.marca} · {row.categoria}</span>
              <button className={`status-badge ${discontinued ? "neutral" : critical ? "danger" : !buyable ? "warning" : row.bajo_punto_reorden ? "warning" : "success"}`} onClick={() => onWarnings(row.sku_id)} aria-label={`Ver alertas de ${row.sku_id}`}>
                <span className="status-dot" />{discontinued ? "Descontinuado" : critical ? "Riesgo de quiebre" : !buyable ? "Revisar datos" : row.bajo_punto_reorden ? "Bajo ROP" : "En nivel"}{rowWarnings.length > 0 && <span className="badge-count">{rowWarnings.length}</span>}
              </button>
            </td>
            <td><span className={`abc-badge abc-${row.clasificacion_abc.toLowerCase()}`}>{row.clasificacion_abc}</span></td>
            <td className="numeric"><span title={`Utilizable: ${number(row.stock_utilizable)} unidades`} className={row.stock_utilizable === 0 ? "text-danger font-semibold" : ""}>{number(row.stock_disponible)}</span>{row.stock_utilizable !== row.stock_disponible && <span className="cell-meta text-danger">{number(row.stock_utilizable)} útiles</span>}</td>
            <td className="numeric"><span>{number(row.stock_en_transito)}</span>{(row.stock_en_transito ?? 0) > 0 && <span className="cell-meta">{number(row.stock_en_transito_a_tiempo)} a tiempo</span>}</td>
            <td className="numeric"><span>{number(row.pronostico_demanda_lead_time, 1)}</span><span className="cell-meta">{row.lead_time_dias} días</span></td>
            <td className="numeric">{number(row.stock_seguridad, 1)}</td><td className="numeric font-semibold">{number(row.punto_reorden, 1)}</td>
            <td className="numeric suggestion-cell"><strong>{number(row.cantidad_sugerida_cajas)} <span>cjs.</span></strong><span className="cell-meta">{number(row.cantidad_sugerida_unidades)} uds.</span></td>
            <td className={`confirmed-cell ${adjusted ? "adjusted-cell" : ""}`}>
              <div className="quantity-control"><input type="number" min={0} max={1_000_000} step={1} inputMode="numeric" aria-label={`Cajas confirmadas ${row.sku_id}`} aria-invalid={!!error} aria-describedby={error ? `error-${row.sku_id}` : undefined} value={value} disabled={disabled || !buyable} onChange={event => onEdit(row, event.target.value)} />{adjusted && <button onClick={() => onReset(row)} disabled={disabled} title="Restaurar sugerencia" aria-label={`Restaurar sugerencia ${row.sku_id}`}><RotateCcw size={12} /></button>}</div>
              <span className="confirmed-cost">{parsed !== null ? usd(parsed * row.unidades_por_caja * row.costo_unitario_usd) : "—"}</span>
              <span className="cell-meta">{parsed !== null ? `${number(parsed * row.unidades_por_caja)} uds.` : "Cantidad pendiente"}{adjusted && <span className="adjusted-tag"> Ajustado</span>}</span>
              {error && <span className="field-error" id={`error-${row.sku_id}`}><AlertTriangle size={11} />{error}</span>}
            </td>
          </tr>;
        })}</tbody>
      </table>
      {rows.length === 0 && <div className="empty-state"><Info size={28} /><h3>Sin productos para estos filtros</h3><p>Prueba con otro proveedor, categoría o término de búsqueda.</p></div>}
    </div>
    <div className="table-footer"><span>Mostrando <strong>{total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)}</strong> de <strong>{total}</strong> SKU</span><span className="unit-legend">Existencias y pronósticos en unidades</span><div className="pagination"><button className="icon-button" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Página anterior"><ChevronLeft size={17} /></button><span>{page} / {Math.max(1, Math.ceil(total / pageSize))}</span><button className="icon-button" disabled={page * pageSize >= total} onClick={() => onPage(page + 1)} aria-label="Página siguiente"><ChevronRight size={17} /></button></div></div>
  </>;
}
