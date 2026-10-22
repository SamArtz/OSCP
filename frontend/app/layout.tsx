import type { Metadata } from "next";
import "./globals.css";
import { DatasetProvider } from "@/components/dataset-provider";

export const metadata: Metadata = {
  title: "Mesa de compras · Abasto",
  description: "Planificación de demanda y órdenes de compra para distribuidoras.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><body><DatasetProvider>{children}</DatasetProvider></body></html>;
}
