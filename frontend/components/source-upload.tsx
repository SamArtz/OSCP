"use client";

import { useState } from "react";
import { FileSpreadsheet, UploadCloud, ArrowRight } from "lucide-react";
import type { Sources, SourceName } from "@/lib/types";

const labels: { name: SourceName; label: string; description: string }[] = [
  { name: "ventas_historicas", label: "Ventas históricas", description: "Movimientos, devoluciones y bonificaciones" },
  { name: "catalogo_sku", label: "Catálogo de productos", description: "SKU, proveedores, costos y restricciones" },
  { name: "inventario_actual", label: "Inventario actual", description: "Existencias por lote y stock en tránsito" },
];

export function SourceUpload({ current, onCalculate, actionLabel = "Calcular sugerencias" }: { current: Sources; onCalculate: (files: Sources) => void; actionLabel?: string }) {
  const [files, setFiles] = useState<Sources>(current);
  const [error, setError] = useState("");
  function select(name: SourceName, file?: File) {
    if (file && (!file.name.toLowerCase().endsWith(".xlsx") || file.size > 10 * 1024 * 1024)) {
      setError("Selecciona un archivo .xlsx de hasta 10 MiB."); return;
    }
    setError(""); setFiles(previous => ({ ...previous, [name]: file }));
  }
  return <form onSubmit={event => { event.preventDefault(); if (!error) onCalculate(files); }}>
    <p className="dialog-description">Carga los tres archivos de tu distribuidora. Un archivo omitido se leerá desde la carpeta de datos del servicio.</p>
    <div className="upload-list">{labels.map(({ name, label, description }) => <div className="upload-field" key={name}>
      <FileSpreadsheet size={25} className="text-accent" />
      <div className="min-w-0 flex-1"><label htmlFor={name}>{label}</label><p>{description}</p><input id={name} type="file" accept=".xlsx" onChange={event => select(name, event.target.files?.[0])} />{files[name] && <span className="file-name">{files[name]!.name} · {(files[name]!.size / 1024).toFixed(0)} KB <button type="button" onClick={() => { select(name); const input = document.getElementById(name) as HTMLInputElement; input.value = ""; }}>Quitar</button></span>}</div>
    </div>)}</div>
    {error && <p className="field-error" role="alert">{error}</p>}
    <div className="source-note"><UploadCloud size={17} /><p>Los archivos se procesan en memoria. No se guardan en el navegador ni se agregan a GitHub.</p></div>
    <button type="submit" className="button-primary w-full justify-center" disabled={!!error}>{actionLabel} <ArrowRight size={17} /></button>
  </form>;
}
