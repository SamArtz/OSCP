# MVP: ingesta ETL y orden de compra sugerida

FastAPI + Pandas para validar ventas, catálogo e inventario de una distribuidora y
generar sugerencias de compra con pronóstico base y estacionalidad semanal.
Los Excel originales no se modifican y las cargas se procesan en memoria, sin guardarlas.
No hay interfaz de usuario ni modelos entrenados con librerías externas.

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

## Paso 2: orden de compra sugerida (OCS)

El motor puro está en `engine.py`; `main.py` reutiliza la lectura y las validaciones
del Paso 1 antes de invocarlo. No se utiliza el preview de cinco filas para calcular
demanda. Se procesan todas las filas válidas, sin variables globales por cliente.
No hacen falta dependencias nuevas.

Con los archivos locales:

```bash
curl -sS -X POST \
  'http://127.0.0.1:8000/api/v1/replenishment/suggested-order?ventana_dias=60&nivel_servicio=0.95&peso_estacional=0.5&dias_revision=0'
```

Con uploads, use los mismos campos multipart `ventas_historicas`, `catalogo_sku`
e `inventario_actual` del primer endpoint. Se pueden mezclar uploads y archivos
locales. La ingesta previa no guarda archivos ni un dataset: si antes cargó por
multipart, debe volver a proporcionar los libros para generar la sugerencia.
También puede probarlo en Swagger mediante `/docs`.

| Parámetro | Predeterminado | Rango |
| --- | ---: | --- |
| `ventana_dias` | 60 | Entero entre 30 y 60 |
| `nivel_servicio` | 0.95 | Mayor que 0.5 y menor que 1 |
| `peso_estacional` | 0.5 | De 0 a 1; cero usa solo promedio ponderado |
| `dias_revision` | 0 | Entero entre 0 y 30; cobertura adicional opcional |

El corte se toma del inventario, no de la fecha del ordenador. Se pronostica desde
el inicio de ese día, usando ventas de días anteriores. Las ventas del corte o
posteriores se excluyen con advertencia. Se asume que el corte representa stock
al inicio del día; si su ERP exporta cierres del día, alinee las fechas de entrada.
No se aceptan horizontes `lead_time_dias + dias_revision` mayores de 730 días.

### Pronóstico y fórmulas

- La demanda observada diaria suma **unidades facturadas + bonificadas**. Las NC
  siguen validadas por el ETL, pero no restan demanda del día en que se emitieron:
  no tenemos la factura original ni evidencia de que la devolución se pueda revender.
- Se reindexa a días calendario, incluyendo días sin movimientos con cero, desde
  el máximo entre el inicio de la ventana y la primera factura histórica del SKU.
  Antes de esa primera observación no se asume que el producto estaba activo.
  El cero representa ausencia de ventas registradas, no prueba disponibilidad.
- Con `n` días, se usan pesos `1, 2, ..., n`, donde el día más reciente pesa más:
  `media = sum(peso * unidades) / sum(pesos)`.
- El componente semanal calcula medias ponderadas por día de semana y factores
  con promedio igual a uno. Se mezcla cada factor con uno según `peso_estacional`.
  Requiere al menos cuatro observaciones de cada día de semana; de lo contrario se
  usa el promedio ponderado. No se intenta aprender estacionalidad anual o feriados.
- `sigma_diaria` es la desviación muestral ponderada de los residuos del perfil
  semanal mezclado. La corrección del denominador es `sum(w) - sum(w²)/sum(w)`.
  El stock de seguridad asume residuos diarios independientes y lead time fijo;
  se usa `NormalDist().inv_cdf(nivel_servicio)`, no 0.95 como valor Z.

```text
L = lead_time_dias del catálogo de cada SKU
R = dias_revision (0 por defecto)
pronostico_L = suma de pronósticos diarios durante L días
SS_L = Z × sigma_diaria × sqrt(L)
ROP = pronostico_L + SS_L

H = L + R
objetivo_H = pronostico_H + Z × sigma_diaria × sqrt(H)
posicion_H = disponible_utilizable + transito_a_tiempo - merma_FEFO_H
faltante = max(0, objetivo_H - posicion_H)
cajas = 0 si faltante == 0
cajas = max(moq_cajas, ceil(faltante / unidades_por_caja)) si faltante > 0
unidades = cajas × unidades_por_caja
costo = unidades × costo_unitario_usd, redondeado a centavos
```

Con `R=0`, el objetivo coincide con el ROP. Si añade revisión, se utiliza la
cobertura `L+R` para sugerir la compra; `bajo_punto_reorden` sigue comparando la
posición al plazo L con el ROP de L. Un plazo cero sin revisión genera objetivo
cero y una advertencia; puede añadir revisión para ese caso.

### Tránsito y FEFO

`stock_en_transito` en la tabla es el total original. Solo
`stock_en_transito_a_tiempo` reduce la necesidad: ETA entre el corte y el final
del horizonte, inclusive. El tránsito atrasado o posterior se expone por separado.
No se restan las reservas otra vez: `stock_disponible` ya corresponde a venta.

FEFO simula el consumo diario priorizando vencimiento, bodega y lote. El
vencimiento es inclusivo y el tránsito se recibe al comienzo del día de su ETA.
Se excluye stock ya vencido y se descuenta únicamente el remanente que vencería
sin consumirse; un lote próximo a vencer que se consume a tiempo sí aporta cobertura.
`prioridad_fefo` devuelve la secuencia, consumo y merma estimados por lote.
No realiza movimientos de almacén.

Las ocho columnas solicitadas se entregan por proveedor/SKU en `orden_sugerida`,
junto a los campos auditables anteriores, unidades de compra y estado. Los costos
son de mercancía, sin IVA ni flete. `resumen_proveedores` suma cajas y costos.
`estado=exito` significa cálculo completado, no ausencia de riesgos. Revise
`estado_sugerencia` y `advertencias` de cada SKU antes de aprobar una compra.

Limitaciones explícitas de este paso:

- No se compra automáticamente un SKU descontinuado, sin historial o sin registro
  de inventario. La ausencia de inventario se devuelve como `null`, no como cero.
  `LANZAMIENTO` con historial sí puede calcularse; se avisa si el historial es corto.
- La señal actual de stock cero no reconstruye rupturas históricas ni corrige
  demanda censurada: la predicción puede subestimar demanda perdida.
- Si una misma OC/SKU repite tránsito en varios lotes/bodegas, se devuelve 422
  `TRANSITO_OC_AMBIGUO`: hace falta desambiguar las líneas antes de sumarlas.
- El tránsito no tiene fecha de caducidad propia en el esquema. Se supone vigente
  durante el horizonte, con advertencia; no se le asigna el vencimiento del lote actual.
- Se informa demanda sin cobertura antes de la llegada de una nueva compra. Una
  compra que llega al final del plazo no soluciona una ruptura previa: requiere
  urgencia o transferencia. La posición de inventario es una comparación de cobertura;
  `stock_fisico_proyectado_horizonte` es la simulación de stock sin ventas perdidas
  convertidas automáticamente en pedidos pendientes.
- Al consolidar varias bodegas se supone transferibilidad y se avisa, porque ventas
  no tiene bodega. No se optimizan rutas ni se distribuyen compras por almacén.
- Se aplica MOQ **por SKU del catálogo**. No se incorporan aún MOQ global del proveedor,
  días de pedido ni feriados de los archivos auxiliares. El plazo del catálogo
  prevalece para este cálculo, sin sustituirlo por el maestro de proveedores.
- Se avisa si la compra supera la demanda estimada en la vida útil nominal. La vida
  residual del lote entrante debe confirmarse antes de emitir una OC.

Uso directo desde Python, con DataFrames ya tipados y validados por el ETL:

```python
import pandas as pd
from engine import ReplenishmentConfig, generate_suggested_order

resultado = generate_suggested_order(
    ventas, catalogo, inventario,
    ReplenishmentConfig(window_days=60, service_level=0.95),
)
tabla_ocs = pd.DataFrame(resultado["orden_sugerida"])
```

Las pruebas del motor verifican valores numéricos conocidos de media, ROP, cajas,
costo, fecha de tránsito y consumo FEFO, además de la integración y regresión ETL.

Ver [INFORME_DATOS.md](INFORME_DATOS.md) para los resultados de los nueve adjuntos.

## Paso 3: mesa de trabajo web

La aplicación Next.js App Router + Tailwind está en [`frontend/`](frontend/README.md).
Con FastAPI iniciado en el puerto 8000, abre otra terminal:

```bash
cd frontend
npm ci
npm run dev
```

Usa Node.js 22.18+ y abre `http://127.0.0.1:3000/replenishment` en tu ordenador.
Incluye filtros de proveedor/categoría/marca, ABC, alertas, cantidades editables,
selección por líneas y descarga XLSX estándar. `FASTAPI_URL` en
`frontend/.env.local` configura la conexión desde el servidor de Next.js.

El OCS ahora incluye `categoria`, `marca`, `clasificacion_abc`, `sku_proveedor`,
`costo_unitario_usd` y `huella_datos` sin quitar campos previos.
El nuevo `POST /api/v1/replenishment/export` acepta multipart con `orden` (JSON)
y los mismos uploads opcionales; valida la huella y vuelve a calcular los costos.
El JSON lleva `fecha_corte`, `huella_datos`, los cuatro parámetros del modelo y
`lineas` con `proveedor_id`, `sku_id` y `cantidad_cajas` confirmadas.
Devuelve el archivo con hojas Orden_Compra, Auditoria y Parametros.
No persiste ajustes, no emite compras ni cambia los Excel originales.

## Paso 4: tablero ejecutivo de capital y riesgo

El tablero está en `/dashboard`, accesible desde la navegación de la app. Sus
cálculos puros viven en [`dashboard.py`](dashboard.py) y los componentes en
[`frontend/components/executive-dashboard.tsx`](frontend/components/executive-dashboard.tsx),
`catalog-health.tsx` y `abc-matrix.tsx`. Comparte navegación y tema con la mesa OCS.

Con FastAPI iniciado, consulta los datos locales:

```bash
curl -sS 'http://127.0.0.1:8000/api/v1/dashboard/metrics?ventana_dias=60'
```

Se lee el catálogo e inventario y **también ventas históricas**, necesarias para
medir cobertura y demanda en riesgo. Se reutiliza el ETL y el pronóstico del
Paso 2. No se utilizan cifras inventadas si falta el histórico.
`ventana_dias` admite 30 a 60 días y vale 60 por defecto.

El `GET` lee los tres libros de `DATA_DIR`. Existe además `POST` en la misma
ruta con los tres uploads opcionales para la carga desde la interfaz. Los
archivos cargados en otra página no se conservan: cada pantalla debe cargarlos
o utilizar los archivos locales del servicio.

### Definiciones de los indicadores

| Indicador | Cálculo |
| --- | --- |
| `capital_sobreinventario_usd` | Por SKU: `max(0, stock_utilizable - 90 × demanda_diaria_ponderada) × costo_unitario_actual`. Se valora solo el excedente, no todo el stock del SKU. |
| `venta_riesgo_quiebre_usd` | Solo Clase A del catálogo: demanda física no cubierta en los próximos 14 días, simulando FEFO y llegadas de tránsito, multiplicada por la proporción estimada de unidades pagadas y el precio de lista. Los bonos consumen stock, pero no crean ingreso. |
| `inventario_riesgo_vencimiento_usd` | Stock disponible de cada lote con vencimiento a **menos de 120 días** del corte, a costo actual. Incluye vencidos; `inventario_vencido_usd` los identifica como subconjunto. Un lote exactamente a 120 días no se incluye. |

Por ejemplo, con demanda de 10 unidades/día, 1.000 unidades utilizables y costo
USD 1, el capital excedente es USD 100 (1.000 − 900), no USD 1.000.
Con 10 unidades de stock, sin tránsito, demanda pagada de 10/día y precio USD 2,
una Clase A tiene USD 260 de venta estimada sin cobertura en 14 días.

El corte del inventario se interpreta como inicio del día, igual que el OCS.
Las ventas del corte o posteriores se excluyen. Los bonos forman parte de la
demanda física; las NC no representan demanda negativa en su fecha de emisión.
La proporción pagada usa los mismos pesos diarios recientes del pronóstico.
No se agregan impuestos ni flete a los precios informados.

Los montos son **exposición estimada**, no pérdidas confirmadas. Los indicadores
se pueden superponer y no deben sumarse como pérdida total. Los lotes ya vencidos
no aportan cobertura ni capital excedente utilizable, pero sí exposición a vencimiento.
Los SKU descontinuados se incluyen para no ocultar existencias inmovilizadas.

### Salud y matriz ABC

Los estados de salud son exclusivos y suman el total del catálogo:

1. `quiebre`: stock utilizable cero **o** demanda sin cobertura proyectada a 14 días.
2. `exceso`: más de 90 días de cobertura, si no está en el estado anterior.
3. `optimo`: inventario e historial conocidos, 14 días cubiertos y sin exceso.
4. `sin_datos`: inventario o historial insuficiente para clasificar; no se fuerza a óptimo.

Un SKU sin facturas históricas no se equipara a demanda cero. Si tiene historia
pero ninguna venta en la ventana reciente, el stock positivo se considera sin
rotación y excedente; se informa esa condición y no se serializa cobertura infinita.
Sin histórico/inventario se excluye el monto que no puede estimarse y se devuelven
conteos en `cobertura_calculo`; el tablero indica estimaciones parciales.

La **matriz 3×3 confirmada** cruza el ABC de volumen del catálogo con ABC de aporte
al margen bruto estimado en la ventana reciente. Fórmula del aporte:

```text
venta_neta_normalizada − costo_actual × (unidades_vendidas_netas + bonos_netos)
```

Las NC se normalizan con `-abs` sin invertir las ya negativas. El margen se estima
a costo actual: no reproduce costos contables históricos, descuentos no registrados
ni la recuperación física de devoluciones dañadas.

Los aportes positivos se ordenan de mayor a menor, usando SKU como desempate.
La clase se decide por participación acumulada **anterior** al SKU: A antes de
80%, B antes de 95%, C el resto. Así el SKU que cruza el umbral permanece en su
clase y el principal contribuyente siempre es A. Aportes conocidos cero/negativos
son C. Los desconocidos se cuentan aparte en `skus_sin_clase_margen`.
Las nueve celdas más los desconocidos suman todos los SKU.

El JSON también devuelve `detalle_skus`, `criterios`, `salud_catalogo`,
`matriz_abc`, `parametros` y avisos del ETL. La interfaz permite abrir cada KPI,
estado de salud o celda ABC para revisar los SKU que lo explican.

## Integridad de SKU, costos y límites decimales

`integrity.py` concentra los contratos de claves. Los cruces con el catálogo
usan explícitamente `on="sku_id"`, `how="left"` y `validate="many_to_one"`,
sin unir por índice ni por posición. Restablecer el índice antes del cruce no
cambia la identidad de los productos. Un SKU desconocido o un catálogo ambiguo
se rechaza antes de calcular; no se selecciona una coincidencia arbitraria.

La carga de catálogo exige `sku_id` único tras recortar espacios y devuelve
HTTP 422 con `SKU_DUPLICADO` si se repite. Ventas puede tener múltiples
movimientos del mismo SKU e inventario varios lotes/bodegas. La clave única
del inventario es `fecha_corte + bodega_id + sku_id + lote`; no se deduplica
ni se exige SKU único a esa granularidad. Los motores también comprueban
estas claves cuando se invocan directamente desde Python.

El importe OCS es exclusivamente `cantidad_sugerida_unidades × costo_unitario_usd`
del catálogo, con `Decimal` y redondeo `ROUND_HALF_UP` a centavos. MOQ y cajas
afectan las unidades compradas, nunca el costo unitario. La exportación utiliza
la misma función; las columnas adicionales en ventas/inventario no sustituyen
el costo ni el tamaño de caja del catálogo.

`stock_policy.py` comparte cobertura y comparación de cantidades entre OCS y
tablero. Ambas se normalizan a **seis decimales**, antes de generar las banderas,
los avisos y sus contadores. Cobertura de 90 días exactos no es sobreinventario;
90,004 sí lo es y se conserva en el JSON y en la tabla, sin mostrarlo como 90.
Los residuos inferiores a la precisión publicada no generan compras ni alertas.
Un producto con historial conocido y demanda reciente cero mantiene la condición
de stock sin rotación; un historial desconocido no se interpreta como cero.

Las respuestas añaden `sobreinventario` y `cobertura_dias` comunes a ambos motores,
`riesgo_quiebre_antes_recepcion` para OCS y `riesgo_quiebre_14_dias` para tablero.
Los contadores de salud se calculan desde el mismo `estado_salud` de las filas;
la bandera OCS y su aviso usan el mismo faltante publicado. Los horizontes
continúan siendo distintos: lead time del proveedor en OCS y 14 días en tablero.
Por ello sus conteos de riesgo no tienen por qué ser iguales.

Regresiones específicas (incluyen SKU-1000/SKU-1009 desordenados y con índices
repetidos, costos distintos, duplicados, lotes válidos y límites decimales):

```bash
python -m unittest discover -s tests -p test_integrity.py -v
```
