"use client";

import type { DashboardResponse } from "@/lib/dashboard";

export function ABCMatrix({ data, selected, onSelect }: { data: DashboardResponse; selected: string; onSelect: (volume: string, margin: string) => void }) {
  const maximum = Math.max(1, ...data.matriz_abc.map(cell => cell.cantidad));
  return <section className="executive-panel abc-panel" aria-labelledby="abc-heading">
    <div className="executive-panel-heading"><div><p className="eyebrow">VOLUMEN × CONTRIBUCIÓN</p><h2 id="abc-heading">Matriz ABC</h2></div><span className="count-badge">3 × 3</span></div>
    <p className="matrix-axis-caption">CLASE POR MARGEN ESTIMADO</p>
    <div className="abc-matrix"><span className="matrix-corner">Vol.</span>{[..."ABC"].map(letter => <span className="matrix-column-label" key={letter}>{letter}</span>)}{[..."ABC"].map(volume => <div className="matrix-row" key={volume}><span className="matrix-row-label">{volume}</span>{[..."ABC"].map(margin => {
      const count = data.matriz_abc.find(cell => cell.volumen === volume && cell.margen === margin)?.cantidad ?? 0;
      return <button key={margin} aria-label={`Volumen ${volume}, margen ${margin}: ${count} SKU`} aria-pressed={selected === volume + margin} className={`matrix-cell ${count ? "has-products" : ""} ${selected === volume + margin ? "chosen" : ""}`} style={count ? { backgroundColor: `color-mix(in srgb, var(--accent) ${8 + count / maximum * 17}%, var(--surface))` } : undefined} onClick={() => onSelect(volume, margin)}><strong>{count}</strong><span>{volume} · {margin}</span></button>;
    })}</div>)}</div>
    <p className="panel-footnote">Volumen: clase del catálogo. Margen: aporte acumulado 80% / 95% en {data.parametros.ventana_dias} días.{data.skus_sin_clase_margen > 0 && <> {data.skus_sin_clase_margen} SKU sin margen estimable.</>}</p>
  </section>;
}
