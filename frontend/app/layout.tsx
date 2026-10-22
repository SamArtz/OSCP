import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Mesa de compras · Abasto",
  description: "Planificación de demanda y órdenes de compra para distribuidoras.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><body>{children}</body></html>;
}
