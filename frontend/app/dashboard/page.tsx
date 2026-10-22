import type { Metadata } from "next";
import { ExecutiveDashboard } from "@/components/executive-dashboard";
export const metadata: Metadata = { title: "Capital y riesgo · Abasto" };
export default function DashboardPage() { return <ExecutiveDashboard />; }
