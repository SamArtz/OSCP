# Paso 1: ingesta y validación ETL

FastAPI + Pandas para validar ventas, catálogo e inventario de una distribuidora.
No contiene modelos ML ni interfaz de usuario. Los Excel originales no se modifican
y las cargas se procesan en memoria, sin guardarlas.

## Ejecutar

Python 3.12 recomendado (versión verificada).

```bash
cd /workspace/OSCP
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Por defecto se leen estos archivos junto a `main.py`:

| Archivo | Hoja de datos |
| --- | --- |
| `ventas_historicas.xlsx` | `Ventas` |
| `catalogo_sku.xlsx` | `Catalogo` |
| `inventario_actual.xlsx` | `Inventario` |

Se ignoran las hojas `Diccionario`. Puede configurar otra carpeta en el servidor
con `DATA_DIR=/ruta/a/datos uvicorn main:app --port 8000`. No se aceptan rutas
proporcionadas por el cliente. Los nueve Excel adjuntos se copiaron localmente a
esta carpeta; `.gitignore` excluye estos datos comerciales del control de versiones.

## Usar el endpoint

Lectura local, sin cuerpo de petición:

```bash
curl -sS -X POST 'http://127.0.0.1:8000/api/v1/ingest/validate?preview_limit=5'
```

Carga multipart de los tres archivos:

```bash
curl -sS -X POST 'http://127.0.0.1:8000/api/v1/ingest/validate?preview_limit=5' \
  -F 'ventas_historicas=@ventas_historicas.xlsx' \
  -F 'catalogo_sku=@catalogo_sku.xlsx' \
  -F 'inventario_actual=@inventario_actual.xlsx'
```

Los tres campos son opcionales individualmente: para cada campo omitido se busca
el archivo local correspondiente. Un upload inválido **no** se reemplaza silenciosamente
por el archivo local. Los nombres de campo no llevan `.xlsx`.

`preview_limit` admite de 1 a 20, con valor inicial 5. La respuesta incluye:

- `estado`: `exito` o `error`.
- `resumen`: origen (`local`/`upload`) y filas leídas de cada hoja. `null` indica
  que el libro no se pudo leer, no cero filas.
- `errores` y `advertencias`: códigos, mensajes, cantidad afectada y hasta diez
  números de fila Excel cuando corresponde. La primera fila de datos es la 2.
- `resumen_procesamiento`: totales de ventas, devoluciones, bonos y stock cero.
- `preview`: filas procesadas de cada archivo, más ejemplos de NC, bonificaciones,
  stock cero y stock agregado por SKU/bodega/corte. Fechas ISO, vacíos JSON `null`.

HTTP 200 puede contener advertencias. HTTP 422 rechaza datos o esquemas inválidos;
HTTP 413 rechaza límites excedidos (10 MiB por libro, 100 MiB descomprimidos,
100.000 filas por hoja). HTTP 500 indica un fallo de lectura local del servidor.
Los errores no incluyen un preview presentado como válido. No se eliminan filas
ni se reemplazan datos faltantes por ceros.

## Esquemas obligatorios

Los encabezados se normalizan a minúsculas y se recortan espacios. Se permiten
columnas adicionales. Cabeceras vacías o duplicadas se rechazan. Todas las columnas
listadas deben existir.

| Archivo | Columnas |
| --- | --- |
| Ventas | `fecha_factura`, `id_documento`, `cliente_id`, `sku_id`, `tipo_doc`, `canal`, `vendedor_id`, `unidades_vendidas`, `unidades_bonificadas`, `precio_unitario_usd`, `venta_neta_usd`, `motivo_nc` |
| Catálogo | `sku_id`, `sku_proveedor`, `ean`, `nombre_producto`, `categoria`, `subcategoria`, `marca`, `presentacion`, `proveedor_id`, `pais_origen`, `unidades_por_caja`, `moq_cajas`, `lead_time_dias`, `vida_util_dias`, `temperatura`, `costo_unitario_usd`, `precio_lista_usd`, `estado`, `clasificacion_abc` |
| Inventario | `fecha_corte`, `bodega_id`, `sku_id`, `lote`, `stock_disponible`, `stock_reservado`, `stock_danado`, `stock_en_transito`, `oc_transito_id`, `fecha_llegada_transito`, `fecha_vencimiento_lote` |

Se requieren valores no vacíos salvo `oc_transito_id` y `fecha_llegada_transito`,
que son obligatorios si `stock_en_transito > 0`. Para facturas use `motivo_nc=Ninguno`.
Fechas: celdas de fecha Excel o texto ISO `YYYY-MM-DD`; se rechazan fechas ambiguas
y números seriales ingresados como celdas numéricas sin formato de fecha.
Cantidades físicas y días deben ser enteros; importes y precios, números finitos.
Catálogo único por SKU/EAN; inventario único por corte/bodega/SKU/lote.
Los SKU de ventas e inventario deben existir en catálogo.

## Reglas de negocio

1. `tipo_doc` define el signo, no el prefijo de `id_documento`.
   `FACTURA` requiere cantidades e importes no negativos. `NOTA_CREDITO` aplica
   `-abs(valor)` a unidades vendidas, bonos e importe en **columnas nuevas**,
   conservando los valores de origen. Una NC negativa no se vuelve positiva.
   Tipos de documento desconocidos se rechazan.
2. `unidades_venta_netas` representa unidades facturadas menos devueltas.
   `unidades_bonificadas_netas` se mantiene separada de la venta pagada.
   `unidades_salida_netas` suma ambas; se exponen bonos entregados y devueltos
   por separado. Los valores de NC con unidades se interpretan como devoluciones
   físicas; una NC puramente financiera debe llevar unidades y bonos iguales a cero.
   Esta métrica no significa que una devolución dañada vuelva al stock vendible:
   el inventario disponible nunca se ajusta a partir de las NC.
3. `posible_demanda_censurada = (stock_disponible == 0)` se añade al inventario.
   También se suma stock por SKU/bodega/corte: un lote vacío con otro lote disponible
   no cuenta como SKU agotado. El stock disponible ya está definido para venta;
   no se restan las reservas otra vez. Stock reservado, dañado o en tránsito no
   se suma al disponible.
4. El corte actual no se une a todas las ventas históricas: introduciría información
   futura y falsas etiquetas. Ventas tampoco contiene bodega. La etiqueta indica
   una posibilidad al corte, sin estimar ventas perdidas. Un SKU ausente de inventario
   genera advertencia y no se convierte artificialmente en stock cero.
5. Se avisa sobre EAN-13 inválidos, posibles descuentos/impuestos en los importes,
   lotes vencidos, tránsito atrasado y stock que no respeta cajas completas. No se
   corrigen estos datos silenciosamente. Los seis archivos auxiliares se revisaron
   en el informe, pero este endpoint solo valida los tres libros de este paso.

## CORS y alcance

Se habilitan `http://localhost:3000` y `http://localhost:5173` para POST.
Puede definir una lista separada por comas en `CORS_ORIGINS` antes de iniciar.
No se habilitan cookies con credenciales. CORS no es autenticación: este módulo
es para desarrollo con un conjunto de archivos. Antes de exponerlo como SaaS
faltan autenticación, aislamiento por distribuidora y límites de carga/concurrencia
en el servidor de entrada. No hay persistencia ni ejecución automática de compras.

## Pruebas

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Las pruebas generan libros sintéticos y cubren cargas multipart/locales/mixtas,
esquemas, fechas, valores inválidos, relaciones SKU, NC de ambos signos, bonos,
stock nulo, lotes, límites, CORS y preservación de originales.

Ver [INFORME_DATOS.md](INFORME_DATOS.md) para los resultados de los nueve adjuntos.
