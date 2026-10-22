"use client";

import { createContext, useContext, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { Sources } from "@/lib/types";

type Dataset = {
  sources: Sources; setSources: Dispatch<SetStateAction<Sources>>;
  windowDays: number; setWindowDays: Dispatch<SetStateAction<number>>;
  sourceLabel: string;
};
const DatasetContext = createContext<Dataset | null>(null);

/** Una selección en memoria por pestaña; no persiste archivos ni los envía a otros usuarios. */
export function DatasetProvider({ children }: { children: React.ReactNode }) {
  const [sources, setSources] = useState<Sources>({});
  const [windowDays, setWindowDays] = useState(60);
  const value = useMemo(() => {
    const uploaded = Object.values(sources).filter(Boolean).length;
    const sourceLabel = uploaded === 0 ? "Archivos del servicio" : uploaded === 3 ? "3 archivos cargados" : `${uploaded} cargados · ${3 - uploaded} del servicio`;
    return { sources, setSources, windowDays, setWindowDays, sourceLabel };
  }, [sources, windowDays]);
  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}

export function useDataset() {
  const context = useContext(DatasetContext);
  if (!context) throw new Error("Falta el proveedor de fuentes de datos.");
  return context;
}
