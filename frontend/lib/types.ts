export interface OCSRow {
  proveedor_id: string;
  sku_id: string;
  sku_proveedor: string;
  nombre_producto: string;
  categoria: string;
  marca: string;
  clasificacion_abc: string;
  costo_unitario_usd: number;
  estado_sku: string;
  estado_sugerencia: string;
  stock_disponible: number | null;
  stock_utilizable: number | null;
  stock_en_transito: number | null;
  stock_en_transito_a_tiempo: number;
  lead_time_dias: number;
  pronostico_demanda_lead_time: number | null;
  stock_seguridad: number | null;
  punto_reorden: number | null;
  bajo_punto_reorden: boolean | null;
  demanda_no_cubierta_antes_recepcion: number | null;
  unidades_por_caja: number;
  moq_cajas: number;
  cantidad_sugerida_cajas: number;
  cantidad_sugerida_unidades: number;
  costo_total_usd: number;
  prioridad_fefo: { bodega_id: string; lote: string; fecha_vencimiento: string; stock_disponible: number; vencido_al_corte: boolean; merma_proyectada_unidades: number; consumo_estimado_unidades: number }[];
}

export interface Warning { sku_id?: string | null; archivo?: string; codigo: string; mensaje: string; cantidad?: number }
export interface ForecastParams { ventana_dias: number; nivel_servicio: number; peso_estacional: number; dias_revision: number }
export interface OCSResponse {
  estado: "exito";
  fecha_corte: string;
  huella_datos: string;
  parametros: ForecastParams;
  orden_sugerida: OCSRow[];
  advertencias: Warning[];
}
export type SourceName = "ventas_historicas" | "catalogo_sku" | "inventario_actual";
export type Sources = Partial<Record<SourceName, File>>;
export type Edits = Record<string, string>;
export type View = "todos" | "quiebre" | "compra" | "ajustes";
