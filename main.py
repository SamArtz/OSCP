"""Paso 1: ingesta Excel y validación ETL, sin persistencia ni modelos ML.

Ejecutar: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Los archivos originales se conservan; todas las transformaciones son en memoria.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR))).resolve()
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024
MAX_ROWS = 100_000
logger = logging.getLogger(__name__)

# Los nombres corresponden a los libros adjuntos, no a la hoja Diccionario.
SCHEMAS = {
    "ventas_historicas": {
        "sheet": "Ventas",
        "text": "id_documento cliente_id sku_id tipo_doc canal vendedor_id motivo_nc".split(),
        "number": "unidades_vendidas unidades_bonificadas precio_unitario_usd venta_neta_usd".split(),
        "date": ["fecha_factura"],
        "optional": [],
    },
    "catalogo_sku": {
        "sheet": "Catalogo",
        "text": (
            "sku_id sku_proveedor ean nombre_producto categoria subcategoria marca "
            "presentacion proveedor_id pais_origen temperatura estado clasificacion_abc"
        ).split(),
        "number": (
            "unidades_por_caja moq_cajas lead_time_dias vida_util_dias "
            "costo_unitario_usd precio_lista_usd"
        ).split(),
        "date": [],
        "optional": [],
    },
    "inventario_actual": {
        "sheet": "Inventario",
        "text": "bodega_id sku_id lote oc_transito_id".split(),
        "number": "stock_disponible stock_reservado stock_danado stock_en_transito".split(),
        "date": "fecha_corte fecha_llegada_transito fecha_vencimiento_lote".split(),
        # Las columnas existen, pero estas dos celdas pueden estar vacías sin tránsito.
        "optional": ["oc_transito_id", "fecha_llegada_transito"],
    },
}

app = FastAPI(title="Ingesta y validación de demanda", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(",")
        if item.strip()
    ],
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)


def issue(issues, archivo, codigo, mensaje, mask=None, **details):
    """Acota los ejemplos; las filas hacen referencia al Excel (cabecera = fila 1)."""
    item = {"archivo": archivo, "codigo": codigo, "mensaje": mensaje, **details}
    if mask is not None:
        selected = mask.fillna(False).astype(bool)
        item["cantidad"] = int(selected.sum())
        item["filas_excel"] = [int(n) + 2 for n in selected[selected].index[:10]]
    issues.append(item)


def check(issues, archivo, codigo, mensaje, mask, **details):
    if mask.fillna(False).any():
        issue(issues, archivo, codigo, mensaje, mask, **details)


def records(df, limit):
    """to_json convierte Timestamp, NaT y escalares NumPy a JSON válido."""
    return json.loads(df.head(limit).to_json(orient="records", date_format="iso"))


class InputProblem(Exception):
    def __init__(self, status_code, codigo, mensaje):
        self.status_code = status_code
        self.codigo = codigo
        self.mensaje = mensaje


def error_status(current, new):
    """Un rechazo por tamaño (413) prevalece sobre errores de datos (422)."""
    priority = {200: 0, 422: 1, 413: 2, 500: 3}
    return max((current, new), key=priority.__getitem__)


def read_book(content, name):
    """Lee una hoja explícita y detecta cabeceras duplicadas antes del mangling."""
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > MAX_EXTRACTED_BYTES:
                raise InputProblem(413, "EXCEL_DEMASIADO_GRANDE", "Excel descomprimido mayor de 100 MiB.")
        with pd.ExcelFile(io.BytesIO(content), engine="openpyxl") as book:
            sheet = SCHEMAS[name]["sheet"]
            if sheet not in book.sheet_names:
                raise InputProblem(422, "HOJA_FALTANTE", f"Se requiere la hoja '{sheet}'.")
            raw = pd.read_excel(
                book, sheet_name=sheet, header=None, dtype=object,
                keep_default_na=False, nrows=MAX_ROWS + 2,
            )
        if raw.empty:
            raise InputProblem(422, "ARCHIVO_VACIO", "La hoja no contiene cabecera ni datos.")
        headers = pd.Index([str(value).strip().lower() for value in raw.iloc[0]])
        if "" in headers or headers.has_duplicates:
            raise InputProblem(422, "CABECERA_INVALIDA", "Hay cabeceras vacías o duplicadas tras normalizarlas.")
        df = raw.iloc[1:].copy().reset_index(drop=True)
        df.columns = headers
        if len(df) > MAX_ROWS:
            raise InputProblem(413, "DEMASIADAS_FILAS", "Máximo 100.000 filas por archivo.")
        if df.empty:
            raise InputProblem(422, "SIN_DATOS", "La hoja contiene cabeceras pero ninguna fila.")
        return df
    except InputProblem:
        raise
    except (BadZipFile, ValueError, KeyError, OSError, EOFError) as exc:
        raise InputProblem(422, "EXCEL_INVALIDO", "No se pudo leer un libro .xlsx válido.") from exc
    except Exception as exc:
        # openpyxl también puede emitir errores XML para libros dañados.
        logger.warning("Lectura Excel fallida (%s)", type(exc).__name__)
        raise InputProblem(422, "EXCEL_INVALIDO", "Libro Excel dañado o no compatible.") from exc


def validate_schema(df, name, errors):
    schema = SCHEMAS[name]
    required = schema["text"] + schema["number"] + schema["date"]
    missing = sorted(set(required) - set(df.columns))
    if missing:
        issue(errors, name, "COLUMNAS_FALTANTES", "Faltan columnas obligatorias.", columnas=missing)
        return False
    initial_errors = len(errors)
    for col in required:
        # Solo se limpian espacios; no se inventan valores ni se eliminan filas.
        df[col] = df[col].map(lambda value: value.strip() if isinstance(value, str) else value)
        df[col] = df[col].map(lambda value: pd.NA if isinstance(value, str) and value == "" else value)
        if col not in schema["optional"]:
            check(errors, name, "VALOR_REQUERIDO", f"'{col}' no admite vacíos.", df[col].isna())
    for col in schema["text"]:
        df[col] = df[col].astype("string")
    for col in schema["number"]:
        original = df[col]
        converted = pd.to_numeric(original, errors="coerce")
        bad = original.notna() & (converted.isna() | ~np.isfinite(converted.astype(float)))
        bad |= original.map(lambda value: isinstance(value, (bool, np.bool_)))
        check(errors, name, "NUMERO_INVALIDO", f"'{col}' debe ser numérico y finito.", bad)
        df[col] = converted
        if col not in {"precio_unitario_usd", "venta_neta_usd", "costo_unitario_usd", "precio_lista_usd"}:
            check(errors, name, "UNIDADES_NO_ENTERAS", f"'{col}' debe contener enteros.", converted.mod(1).ne(0) & converted.notna())
    for col in schema["date"]:
        original = df[col]
        # Evita interpretar números como nanosegundos o fechas ambiguas DD/MM-MM/DD.
        iso_or_date = original.map(
            lambda value: isinstance(value, (date, datetime, pd.Timestamp))
            or (isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T].*)?", value)))
        )
        converted = pd.to_datetime(original.where(iso_or_date), format="mixed", errors="coerce", utc=True).dt.tz_convert(None)
        check(errors, name, "FECHA_INVALIDA", f"'{col}': use fecha Excel o ISO YYYY-MM-DD.", original.notna() & converted.isna())
        df[col] = converted
    check(errors, name, "FILAS_DUPLICADAS", "Hay filas idénticas; no se eliminan automáticamente.", df.duplicated(keep=False))
    return len(errors) == initial_errors


def validate_business(tables, errors, warnings):
    sales, catalog, inventory = (tables[n] for n in SCHEMAS)
    sn, cn, inn = SCHEMAS.keys()
    sales["tipo_doc"] = sales["tipo_doc"].str.upper()
    catalog["estado"] = catalog["estado"].str.upper()
    catalog["clasificacion_abc"] = catalog["clasificacion_abc"].str.upper()
    check(errors, sn, "TIPO_DOCUMENTO_INVALIDO", "Solo FACTURA y NOTA_CREDITO están soportados.", ~sales.tipo_doc.isin(["FACTURA", "NOTA_CREDITO"]))
    nc = sales.tipo_doc.eq("NOTA_CREDITO")
    for col in ["unidades_vendidas", "unidades_bonificadas", "venta_neta_usd"]:
        check(errors, sn, "FACTURA_NEGATIVA", f"'{col}' negativo en FACTURA.", ~nc & sales[col].lt(0))
        check(warnings, sn, "SIGNO_NC_NORMALIZADO", f"'{col}' positivo en NC: se aplicará -abs(valor).", nc & sales[col].gt(0))
    check(errors, sn, "PRECIO_NEGATIVO", "El precio unitario no puede ser negativo.", sales.precio_unitario_usd.lt(0))
    check(errors, sn, "MOTIVO_NC_FALTANTE", "Indique el motivo de la nota de crédito.", nc & sales.motivo_nc.str.casefold().isin(["ninguno", "no aplica", "n/a"]))
    check(warnings, sn, "LINEA_REPETIDA", "Documento/SKU repetido; confirme líneas distintas con un id de línea.", sales.duplicated(["id_documento", "sku_id"], keep=False))
    check(errors, cn, "SKU_DUPLICADO", "sku_id debe ser único en el catálogo.", catalog.sku_id.duplicated(keep=False))
    check(errors, cn, "ESTADO_INVALIDO", "Estado esperado: ACTIVO, DESCONTINUADO o LANZAMIENTO.", ~catalog.estado.isin(["ACTIVO", "DESCONTINUADO", "LANZAMIENTO"]))
    check(errors, cn, "ABC_INVALIDO", "Clasificación esperada: A, B o C.", ~catalog.clasificacion_abc.isin(["A", "B", "C"]))
    for col in ["unidades_por_caja", "moq_cajas", "vida_util_dias"]:
        check(errors, cn, "PARAMETRO_NO_POSITIVO", f"'{col}' debe ser mayor que cero.", catalog[col].le(0))
    for col in ["lead_time_dias", "costo_unitario_usd", "precio_lista_usd"]:
        check(errors, cn, "PARAMETRO_NEGATIVO", f"'{col}' no puede ser negativo.", catalog[col].lt(0))
    check(errors, cn, "EAN_DUPLICADO", "Un EAN identifica más de un SKU.", catalog.ean.duplicated(keep=False))

    def valid_ean(value):
        if len(value) != 13 or not value.isascii() or not value.isdigit():
            return False
        checksum = -sum(int(digit) * (1 if pos % 2 == 0 else 3) for pos, digit in enumerate(value[:12])) % 10
        return checksum == int(value[-1])

    check(warnings, cn, "EAN_INVALIDO", "EAN-13 con longitud o dígito verificador incorrecto.", ~catalog.ean.map(valid_ean))
    check(warnings, cn, "PRECIO_MENOR_COSTO", "Precio de lista inferior al costo.", catalog.precio_lista_usd.lt(catalog.costo_unitario_usd))
    for name, df in [(sn, sales), (inn, inventory)]:
        check(errors, name, "SKU_DESCONOCIDO", "Hay SKU que no existen en el catálogo.", ~df.sku_id.isin(catalog.sku_id))
    check(errors, inn, "LOTE_DUPLICADO", "Se repite fecha/bodega/SKU/lote.", inventory.duplicated(["fecha_corte", "bodega_id", "sku_id", "lote"], keep=False))
    for col in SCHEMAS[inn]["number"]:
        check(errors, inn, "STOCK_NEGATIVO", f"'{col}' no puede ser negativo.", inventory[col].lt(0))
    transit = inventory.stock_en_transito.gt(0)
    check(errors, inn, "TRANSITO_INCOMPLETO", "Stock en tránsito requiere OC y fecha de llegada.", transit & (inventory.oc_transito_id.isna() | inventory.fecha_llegada_transito.isna()))
    check(warnings, inn, "TRANSITO_SIN_STOCK", "Hay OC/fecha de llegada sin unidades en tránsito.", ~transit & (inventory.oc_transito_id.notna() | inventory.fecha_llegada_transito.notna()))
    check(warnings, inn, "TRANSITO_ATRASADO", "Llegada prevista anterior al corte con tránsito pendiente.", transit & inventory.fecha_llegada_transito.lt(inventory.fecha_corte))
    check(warnings, inn, "STOCK_VENCIDO", "Stock disponible con lote vencido a la fecha del corte.", inventory.stock_disponible.gt(0) & inventory.fecha_vencimiento_lote.lt(inventory.fecha_corte))
    if inventory.fecha_corte.nunique() != 1:
        issue(errors, inn, "CORTES_MEZCLADOS", "El inventario actual debe representar un único corte.")
    if errors:
        return
    box = inventory.sku_id.map(catalog.set_index("sku_id").unidades_por_caja)
    check(warnings, inn, "STOCK_NO_MULTIPLO_CAJA", "Disponible no múltiplo de caja según el diccionario; confirme fraccionamiento.", inventory.stock_disponible.mod(box).ne(0))
    check(warnings, cn, "SKU_SIN_INVENTARIO", "SKU del catálogo sin registro de inventario; no se asume stock cero.", ~catalog.sku_id.isin(inventory.sku_id))
    check(warnings, sn, "VENTA_POSTERIOR_CORTE", "Hay ventas posteriores al corte del inventario actual.", sales.fecha_factura.gt(inventory.fecha_corte.max()))


def process(tables, warnings, limit):
    sales, catalog, inventory = (tables[n] for n in SCHEMAS)
    nc = sales.tipo_doc.eq("NOTA_CREDITO")
    # Signo idempotente: una NC que ya es negativa sigue siendo negativa.
    sales["es_nota_credito"] = nc
    sales["unidades_venta_netas"] = sales.unidades_vendidas.where(~nc, -sales.unidades_vendidas.abs())
    sales["unidades_bonificadas_netas"] = sales.unidades_bonificadas.where(~nc, -sales.unidades_bonificadas.abs())
    sales["venta_neta_normalizada_usd"] = sales.venta_neta_usd.where(~nc, -sales.venta_neta_usd.abs())
    sales["tiene_bonificacion"] = sales.unidades_bonificadas.ne(0)
    sales["unidades_devueltas"] = sales.unidades_venta_netas.where(nc, 0).abs()
    # Las bonificaciones no son venta pagada; sí consumen inventario físico.
    sales["unidades_salida_netas"] = sales.unidades_venta_netas + sales.unidades_bonificadas_netas
    expected = sales.unidades_venta_netas * sales.precio_unitario_usd
    check(warnings, "ventas_historicas", "IMPORTE_DIFIERE", "Importe distinto a unidades × precio (tolerancia USD 0,01); confirme descuentos/impuestos.", expected.sub(sales.venta_neta_normalizada_usd).abs().gt(0.010001))
    inventory["posible_demanda_censurada"] = inventory.stock_disponible.eq(0)
    inventory["lote_vencido"] = inventory.fecha_vencimiento_lote.lt(inventory.fecha_corte)
    # Un lote vacío no implica que todo el SKU esté agotado en esa bodega.
    stock = inventory.groupby(["fecha_corte", "bodega_id", "sku_id"], as_index=False).agg(stock_disponible=("stock_disponible", "sum"))
    stock["posible_demanda_censurada"] = stock.stock_disponible.eq(0)
    issue(warnings, "inventario_actual", "CENSURA_SOLO_EN_CORTE", "La etiqueta es una señal del corte actual, no prueba demanda perdida ni se propaga a ventas históricas. Ventas no incluye bodega_id.")
    bonus = sales.unidades_bonificadas_netas
    net = sales.unidades_venta_netas
    return {
        "ventas": {
            "facturas": int((~nc).sum()), "notas_credito": int(nc.sum()),
            "unidades_facturadas": int(net[~nc].sum()),
            "unidades_devueltas": int(sales.unidades_devueltas.sum()),
            "unidades_venta_netas": int(net.sum()),
            "filas_con_bonificacion": int(sales.tiene_bonificacion.sum()),
            "unidades_bonificadas_entregadas": int(bonus[~nc].sum()),
            "unidades_bonificadas_devueltas": int(bonus[nc].abs().sum()),
            "unidades_bonificadas_netas": int(bonus.sum()),
            "unidades_salida_netas": int(sales.unidades_salida_netas.sum()),
            "venta_neta_normalizada_usd": round(float(sales.venta_neta_normalizada_usd.sum()), 2),
            "fecha_desde": sales.fecha_factura.min().isoformat(),
            "fecha_hasta": sales.fecha_factura.max().isoformat(),
        },
        "inventario": {
            "fecha_corte": inventory.fecha_corte.iloc[0].isoformat(),
            "filas_stock_cero": int(inventory.posible_demanda_censurada.sum()),
            "sku_bodega_sin_stock": int(stock.posible_demanda_censurada.sum()),
            "sku_sin_stock": stock.loc[stock.posible_demanda_censurada, "sku_id"].drop_duplicates().tolist(),
        },
        "preview": {
            **{name: records(df, limit) for name, df in tables.items()},
            "notas_credito": records(sales.loc[nc], limit),
            "bonificaciones": records(sales.loc[sales.tiene_bonificacion], limit),
            "inventario_stock_cero": records(inventory.loc[inventory.posible_demanda_censurada], limit),
            "stock_por_sku_bodega": records(stock, limit),
        },
    }


def validate_contents(contents, summary, errors, limit, status_code=200):
    tables, warnings = {}, []
    for name, content in contents.items():
        try:
            df = read_book(content, name)
        except InputProblem as exc:
            issue(errors, name, exc.codigo, exc.mensaje)
            status_code = error_status(status_code, exc.status_code)
            continue
        summary[name]["filas_leidas"] = len(df)
        if validate_schema(df, name, errors):
            tables[name] = df
    if not errors:
        validate_business(tables, errors, warnings)
    result = {"estado": "error" if errors else "exito", "resumen": summary, "errores": errors, "advertencias": warnings, "preview": {}}
    if errors:
        return JSONResponse(status_code=error_status(status_code, 422), content=result)
    processed = process(tables, warnings, limit)
    result["resumen_procesamiento"] = {k: v for k, v in processed.items() if k != "preview"}
    result["preview"] = processed["preview"]
    return JSONResponse(content=result)


def read_local(name):
    # No se aceptan rutas del cliente ni se usa el nombre del upload como ruta.
    path = DATA_DIR / f"{name}.xlsx"
    try:
        with path.open("rb") as stream:
            return stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError as exc:
        raise InputProblem(422, "ARCHIVO_FALTANTE", f"Falta {name}.xlsx en DATA_DIR; también puede cargarlo por multipart.") from exc
    except OSError as exc:
        raise InputProblem(500, "LECTURA_LOCAL_FALLIDA", "El servidor no pudo leer el archivo local.") from exc


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    # No devolver el input de Pydantic: puede incluir contenido binario del usuario.
    return JSONResponse(status_code=422, content={
        "estado": "error", "resumen": {}, "preview": {}, "advertencias": [],
        "errores": [{"codigo": "SOLICITUD_INVALIDA", "mensaje": item["msg"], "campo": list(item["loc"])} for item in exc.errors()],
    })


@app.post("/api/v1/ingest/validate")
async def ingest_validate(
    ventas_historicas: UploadFile | None = File(default=None),
    catalogo_sku: UploadFile | None = File(default=None),
    inventario_actual: UploadFile | None = File(default=None),
    preview_limit: int = Query(default=5, ge=1, le=20),
):
    """Cada upload omitido se busca en DATA_DIR (por defecto, junto a main.py).

    Solo valida y procesa en memoria: no guarda uploads ni modifica los Excel.
    Una respuesta 200 puede contener advertencias; 422 indica datos inválidos.
    """
    uploads = dict(zip(SCHEMAS, [ventas_historicas, catalogo_sku, inventario_actual]))
    contents, summary, errors = {}, {}, []
    status_code = 200
    for name, upload in uploads.items():
        summary[name] = {"origen": "upload" if upload is not None else "local", "filas_leidas": None}
        try:
            if upload is not None:
                if Path(upload.filename or "").suffix.lower() != ".xlsx":
                    raise InputProblem(422, "EXTENSION_INVALIDA", "Solo se admiten archivos .xlsx.")
                content = await upload.read(MAX_FILE_BYTES + 1)
            else:
                content = await run_in_threadpool(read_local, name)
            if len(content) > MAX_FILE_BYTES:
                raise InputProblem(413, "ARCHIVO_DEMASIADO_GRANDE", "Máximo 10 MiB por archivo.")
            contents[name] = content
        except InputProblem as exc:
            issue(errors, name, exc.codigo, exc.mensaje)
            status_code = error_status(status_code, exc.status_code)
        finally:
            if upload is not None:
                await upload.close()
    # Pandas/openpyxl son bloqueantes: no se ejecutan sobre el event loop.
    return await run_in_threadpool(validate_contents, contents, summary, errors, preview_limit, status_code)
