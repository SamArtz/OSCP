"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CircleHelp, ClipboardList, Layers3, LayoutDashboard, Moon, ShieldCheck, Sun } from "lucide-react";

export function WorkspaceShell({ section, onHelp, children }: {
  section: "dashboard" | "replenishment"; onHelp: () => void; children: React.ReactNode;
}) {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    let preferred = false;
    try { preferred = localStorage.getItem("abasto-theme") === "dark"; } catch { /* El tema no debe bloquear la aplicación. */ }
    setDark(preferred); document.documentElement.classList.toggle("dark", preferred);
  }, []);
  function toggleTheme() {
    const next = !dark;
    setDark(next); document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("abasto-theme", next ? "dark" : "light"); } catch { /* Preferencia opcional. */ }
  }
  const links = [
    { id: "dashboard", href: "/dashboard", label: "Tablero ejecutivo", icon: <LayoutDashboard size={18} /> },
    { id: "replenishment", href: "/replenishment", label: "Mesa de compras", icon: <ClipboardList size={18} /> },
  ];
  return <div className="app-shell">
    <aside className="sidebar">
      <Link className="brand" href="/dashboard" aria-label="Abasto, tablero ejecutivo"><div className="brand-symbol"><Layers3 size={23} strokeWidth={1.7} /></div><span>abasto<span className="brand-period">.</span></span></Link>
      <div className="workspace-label"><span className="workspace-avatar">D</span><div><strong>Distribuidora</strong><span>El Salvador · B2B</span></div></div>
      <p className="nav-section">PLANIFICACIÓN</p>
      <nav>{links.map(link => <Link key={link.id} href={link.href} className={`nav-item ${section === link.id ? "active" : ""}`} aria-current={section === link.id ? "page" : undefined} title={link.label}>{link.icon}<span>{link.label}</span>{section === link.id && <span className="nav-indicator" />}</Link>)}<button className="nav-item" onClick={onHelp} title="Guía de trabajo"><CircleHelp size={18} /><span>Guía de trabajo</span></button></nav>
      <div className="sidebar-bottom"><div className="sidebar-note"><ShieldCheck size={19} /><p>Decisiones informadas.<br /><strong>Compras bajo tu control.</strong></p></div><div className="sidebar-person"><span className="person-avatar">CP</span><div><strong>Equipo de compras</strong><span>Mesa operativa</span></div></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><span>Operaciones</span><span className="breadcrumb-slash">/</span><strong>{section === "dashboard" ? "Capital y riesgo" : "Reabastecimiento"}</strong></div><div className="topbar-actions"><span className="market-label">El Salvador <span>USD</span></span><span className="vertical-divider" /><button className="icon-button" aria-label={dark ? "Activar modo claro" : "Activar modo oscuro"} onClick={toggleTheme}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button><button className="icon-button" onClick={onHelp} aria-label={section === "dashboard" ? "Criterios del tablero" : "Ayuda de la mesa de trabajo"}><CircleHelp size={18} /></button><span className="top-avatar">CP</span></div></header>
      <nav className="mobile-workspace-nav" aria-label="Secciones">{links.map(link => <Link key={link.id} href={link.href} aria-current={section === link.id ? "page" : undefined}>{link.icon}{link.label}</Link>)}</nav>
      {children}
    </div>
  </div>;
}
