"""Contratos de claves compartidos por el ETL y los motores de cálculo."""

import pandas as pd


class EngineInputError(ValueError):
    """Datos ambiguos o incompletos que no se deben convertir en una compra."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_sku_keys(frame: pd.DataFrame, name: str, *, unique: bool = False):
    if "sku_id" not in frame.columns:
        raise EngineInputError("COLUMNAS_FALTANTES", f"{name}: falta sku_id.")
    valid = frame.sku_id.map(lambda value: isinstance(value, str) and bool(value.strip()) and value == value.strip())
    if not valid.all():
        raise EngineInputError("SKU_INVALIDO", f"{name}: sku_id debe ser texto no vacío y sin espacios exteriores.")
    if unique and frame.sku_id.duplicated(keep=False).any():
        raise EngineInputError("SKU_DUPLICADO", f"{name}: sku_id debe ser único; no se elige una fila arbitrariamente.")


def validate_sku_integrity(sales: pd.DataFrame, catalog: pd.DataFrame, inventory: pd.DataFrame):
    """El catálogo es único; movimientos y lotes conservan su granularidad."""
    if catalog.empty or inventory.empty:
        raise EngineInputError("SIN_DATOS", "Catálogo e inventario requieren al menos una fila.")
    validate_sku_keys(catalog, "catalogo_sku", unique=True)
    for name, frame in [("ventas_historicas", sales), ("inventario_actual", inventory)]:
        validate_sku_keys(frame, name)
        if not frame.sku_id.isin(catalog.sku_id).all():
            raise EngineInputError("SKU_DESCONOCIDO", f"{name}: hay SKU que no existen en el catálogo.")
    if inventory.duplicated(["fecha_corte", "bodega_id", "sku_id", "lote"], keep=False).any():
        raise EngineInputError("LOTE_DUPLICADO", "Se repite fecha/bodega/SKU/lote; no se suma stock duplicado.")


def join_catalog(frame: pd.DataFrame, catalog: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Cruce muchos-a-uno exclusivamente por SKU, sin alinear por índice.

    Se conserva el orden izquierdo y se restaura su índice solo como etiqueta
    de fila (por ejemplo para informar la fila Excel). Ningún valor se cruza
    mediante ese índice. No modifica los DataFrames originales.
    """
    validate_sku_keys(catalog, "catalogo_sku", unique=True)
    validate_sku_keys(frame, "datos")
    if not frame.sku_id.isin(catalog.sku_id).all():
        raise EngineInputError("SKU_DESCONOCIDO", "No se puede cruzar un SKU ausente del catálogo.")
    if set(columns) & set(frame.columns):
        raise EngineInputError("COLUMNAS_AMBIGUAS", "El cruce intentaría sobrescribir columnas de origen.")
    joined = frame.reset_index(drop=True).merge(
        catalog[["sku_id", *columns]].reset_index(drop=True),
        on="sku_id", how="left", validate="many_to_one", sort=False,
    )
    joined.index = frame.index.copy()
    return joined
