"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

export function Dialog({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { dialog?.close(); document.body.style.overflow = previous; };
  }, []);
  return <dialog ref={ref} className="workspace-dialog" aria-labelledby="dialog-title" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="dialog-inner">
      <div className="dialog-heading"><div><p className="eyebrow">MESA DE COMPRAS</p><h2 id="dialog-title">{title}</h2></div><button className="icon-button" onClick={onClose} aria-label="Cerrar diálogo"><X size={20} /></button></div>
      {children}
    </div>
  </dialog>;
}
