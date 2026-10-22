"use client";

import { healthColors, healthLabels, healthShares } from "@/lib/dashboard";
import type { DashboardResponse, HealthState } from "@/lib/dashboard";

export function CatalogHealth({ data, selected, onSelect }: { data: DashboardResponse; selected: string; onSelect: (key: HealthState) => void }) {
  const segments = healthShares(data.salud_catalogo);
  const circumference = 2 * Math.PI * 67;
  let offset = 0;
  return <section className="executive-panel health-panel" aria-labelledby="health-heading">
    <div className="executive-panel-heading"><div><p className="eyebrow">DISPONIBILIDAD Y ROTACIÓN</p><h2 id="health-heading">Salud del catálogo</h2></div><span className="count-badge">{data.total_skus} SKU</span></div>
    <div className="catalog-health-body">
      <svg className="health-ring" viewBox="0 0 180 180" role="img" aria-label={segments.map(part => `${healthLabels[part.key]}: ${part.count}`).join(". ")}>
        <circle cx="90" cy="90" r="67" fill="none" stroke="var(--border)" strokeWidth="17" />
        {segments.map(part => {
          const length = part.share * circumference;
          const start = offset; offset += length;
          return length > 0 ? <circle key={part.key} cx="90" cy="90" r="67" fill="none" stroke={healthColors[part.key]} strokeWidth="17" strokeDasharray={`${Math.max(0, length - 3)} ${circumference - length + 3}`} strokeDashoffset={-start} transform="rotate(-90 90 90)" /> : null;
        })}
        <text x="90" y="88" textAnchor="middle" className="ring-value">{data.total_skus}</text><text x="90" y="108" textAnchor="middle" className="ring-caption">SKU analizados</text>
      </svg>
      <div className="health-legend">{segments.map(part => <button key={part.key} aria-pressed={selected === part.key} onClick={() => onSelect(part.key)} className={selected === part.key ? "chosen" : ""}><span className="legend-color" style={{ background: healthColors[part.key] }} /><div><strong>{healthLabels[part.key]}</strong><span>{part.key === "quiebre" ? "Actual o proyectado a 14 días" : part.key === "exceso" ? "Más de 90 días de cobertura" : part.key === "optimo" ? "14 días cubiertos y sin exceso" : "Historial o inventario pendiente"}</span></div><b>{part.count}</b><span className="legend-percent">{Math.round(part.share * 100)}%</span></button>)}</div>
    </div><p className="panel-footnote">Cada SKU ocupa un solo estado. Selecciona una señal para revisar sus productos.</p>
  </section>;
}
