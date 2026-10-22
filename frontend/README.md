# Mesa de trabajo OCS

Next.js App Router + TypeScript + Tailwind CSS 4. La ruta `/` redirige a
`/replenishment`. Diseño corporativo claro/oscuro con tabla, filtros, selección,
ajustes de compra y descarga XLSX estándar.

## Iniciar en tu ordenador

Usa **Node.js 22.18+** (verificado con Node 24). Abre dos terminales.

**Terminal 1: FastAPI**, desde la raíz de OSCP, con tu entorno Python activado:

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

**Terminal 2: Next.js**:

```bash
cd frontend
npm ci
npm run dev
```

Abre `http://127.0.0.1:3000/replenishment` en tu navegador.

La pantalla intenta calcular con los archivos locales de FastAPI. Si faltan,
pulsa **Cargar archivos** y selecciona ventas, catálogo e inventario. Puedes
cargar los tres o mezclar uploads con archivos locales del servicio.
Los archivos comerciales no están incluidos en Git.

## Conexión con FastAPI

Sin configuración adicional, Next.js conecta con `http://127.0.0.1:8000`.
Para cambiarlo, copia `.env.example` a `.env.local` y modifica:

```dotenv
FASTAPI_URL=http://127.0.0.1:8000
```

Reinicia Next.js después de cambiar esta variable. No necesita el prefijo
`NEXT_PUBLIC_`: la dirección es del servidor de Next.js, no del navegador.
Si utilizas contenedores, esta dirección debe apuntar al servicio FastAPI desde
el contenedor de Next.js; `127.0.0.1` solo sirve cuando están en la misma máquina.

Los Route Handlers actúan como proxy de destino fijo:

| Navegador → Next.js | Next.js → FastAPI |
| --- | --- |
| `POST /api/replenishment` | `POST /api/v1/replenishment/suggested-order` |
| `POST /api/replenishment/export` | `POST /api/v1/replenishment/export` |

Esto evita configurar CORS en el navegador para esta interfaz. No añade
autenticación ni aislamiento de clientes: se conserva el alcance local del MVP.
Hay que actualizar **también el backend** de este paso: agrega metadatos de
catálogo, huella de archivos y el endpoint XLSX. No basta con ejecutar el nuevo
frontend contra el backend del Paso 2.

## Componentes principales

| Archivo | Responsabilidad |
| --- | --- |
| `app/replenishment/page.tsx` | Ruta App Router |
| `components/replenishment-desk.tsx` | Cálculo, filtros, selección, métricas y edición |
| `components/order-table.tsx` | Tabla, cajas confirmadas, selección por página y paginación |
| `components/source-upload.tsx` | Carga de los tres archivos y límite de 10 MiB por libro |
| `components/dialog.tsx` | Diálogo accesible con cierre por Escape |
| `lib/api.ts` | Cliente OCS, contrato y descarga |
| `lib/ocs.ts` | Reglas de cantidades, filtros y totales |
| `lib/types.ts` | Contratos TypeScript |
| `lib/proxy.ts` | Conexión del servidor con FastAPI |
| `app/globals.css` | Tailwind y estilos corporativos adaptables |

## Flujo del comprador

1. Filtra por proveedor, categoría o marca; busca SKU/producto sin depender de
   acentos. `/` lleva el foco a la búsqueda. Los filtros no alteran la selección.
2. Las columnas de stock, tránsito, pronóstico, seguridad y ROP están en **unidades**.
   La sugerencia muestra **cajas y unidades**. El costo usa el valor unitario del catálogo,
   incluso cuando la sugerencia original es cero.
3. Edita **Compra confirmada** en cajas enteras. Debe ser cero o al menos el MOQ.
   El importe se actualiza inmediatamente. Una cantidad inválida seleccionada
   bloquea la descarga y muestra el motivo junto al input.
4. Inicialmente se seleccionan los SKU comprables con sugerencia positiva. Editar
   una cantidad positiva selecciona la línea; ingresar cero la deselecciona. El
   checkbox del encabezado afecta solo las líneas comprables de la página actual.
5. Descarga todas las líneas **seleccionadas**, incluidas las ocultas por filtros
   y paginación. El resumen inferior indica el alcance y el importe total.

Los SKU descontinuados, sin historial o sin inventario conocido muestran su estado
y no se pueden comprar desde esta mesa. Las etiquetas de riesgo abren avisos y
detalle FEFO. El centro de alertas conserva también los avisos generales de calidad.
La predicción es el baseline del Paso 2; la etiqueta “IA” no implica un modelo
adicional o un LLM.

Los ajustes y archivos viven solo en memoria durante la sesión: recargar o
recalcular descarta los ajustes. Los archivos y la ventana se comparten entre
mesa y tablero al navegar en la misma pestaña; una recarga completa los descarta. Se pide confirmación antes de recalcular si hay
cambios. Solo se conserva la preferencia de tema en `localStorage`.

## Formato de descarga elegido

Se utiliza **XLSX estándar**, sin prometer compatibilidad con un ERP específico:

- `Orden_Compra`: proveedor, SKU interno, código del proveedor, descripción,
  cajas confirmadas, unidades por caja, unidades totales, costo unitario y total.
- `Auditoria`: sugerencia original, cantidad confirmada y diferencia por SKU.
- `Parametros`: corte de inventario, huella de los archivos y parámetros del modelo.

El backend vuelve a validar archivos y cantidades y calcula los costos desde
el catálogo. El frontend no puede imponer precios mediante el payload. La huella
evita descargar contra archivos modificados desde la última OCS; si cambian,
devuelve **409** y se debe recalcular. Los campos de texto se escriben como texto,
sin convertir nombres que comiencen con `=` en fórmulas de Excel.

La descarga agrupa las líneas por proveedor/SKU en **un libro**, con importes de
mercancía sin IVA ni flete. No registra ni envía una compra al ERP.

## Verificación

```bash
npm test
npm run typecheck
npm run build
npm start
```

`npm test` ejecuta pruebas de cajas/MOQ, edición, selección global, filtros y
productos descontinuados. Desde la raíz se ejecutan las pruebas de backend y XLSX:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

La pantalla incluye estados de carga, errores de conexión, errores de esquema,
tablas sin coincidencias, restauración de sugerencias y avisos de exportación.
Un fallo de actualización mantiene la tabla anterior visible y bloquea su descarga.

Prueba de navegador opcional, con ambos servidores iniciados y los tres Excel
originales junto a `main.py` (se requiere al menos un SKU con compra sugerida):

```bash
python -m pip install playwright
python -m playwright install chromium
python frontend/tests/browser_smoke.py
```

Ejecuta el último comando desde la raíz del repositorio. `CHROMIUM_PATH` permite
usar un Chromium instalado; `FRONTEND_URL` cambia la dirección de la app y
`BROWSER_OUTPUT_DIR` la carpeta de descargas/capturas de prueba. El script verifica
filtros, ajustes, descarga con cantidades confirmadas, carga real de los tres
Excel, temas, diseño móvil y errores de conexión. Sus archivos quedan en la
carpeta temporal del sistema, sin modificar las fuentes.

## Tablero ejecutivo (`/dashboard`)

La navegación lateral, y las pestañas en móvil, conectan la mesa OCS con el nuevo
tablero. No hacen falta dependencias nuevas ni otra configuración de conexión.
Actualiza también FastAPI al Paso 4 antes de iniciar la interfaz.

| Archivo | Responsabilidad |
| --- | --- |
| `components/workspace-shell.tsx` | Navegación y tema comunes para ambas páginas |
| `components/executive-dashboard.tsx` | KPI, filtros, actualización, carga y detalle |
| `components/catalog-health.tsx` | Anillo y leyenda interactiva de salud |
| `components/abc-matrix.tsx` | Matriz 3×3 de volumen y margen |
| `lib/dashboard.ts` | Contratos, filtros y proporciones |
| `app/api/dashboard/route.ts` | Proxy GET/POST a `/api/v1/dashboard/metrics` |

Los tres KPI muestran capital excedente a más de 90 días, venta Clase A en riesgo
a 14 días y stock en lotes con menos de 120 días remanentes. Consulta las fórmulas
en **Ver criterios**: los montos de inventario están a costo; los de venta, a lista.
No se presentan como pérdidas confirmadas ni se suman entre sí.

- Al abrir la página se consulta el `GET` de archivos locales. **Cargar archivos**
  usa la variante multipart sin persistir libros ni compartir archivos entre clientes.
- Pulsa un KPI para ver sus contribuyentes, una señal de salud para filtrar por
  estado o una celda ABC para cruzar volumen y margen.
- **Ver catálogo completo** limpia los filtros y muestra también los SKU con
  exposición cero o datos insuficientes. `—` significa no estimable, no cero.
- Un monto cero de vencimiento es válido: significa que no hay stock en lotes
  dentro del umbral, no que el servicio falló.
- Si falla una actualización, se conserva el cálculo previo con un aviso de
  antigüedad. La ventana puede cambiar entre 30 y 60 días.

La salud incluye quiebre actual **o proyectado en 14 días**; por eso no equivale
al simple conteo de stock cero del ETL o al riesgo dentro del lead time variable
del OCS. Los casos sin datos se separan para no mostrarlos como saludables.

Con los nueve archivos de referencia y corte 21/10/2026, usando 60 días, se
verificaron USD 8.840,14 de excedente, USD 291,65 de venta Clase A en riesgo y
USD 0 de exposición a vencimiento. La salud suma 11 + 22 + 17 = 50 SKU.

Para probar el tablero con navegador, ambos servidores iniciados y los archivos
originales locales, ejecuta desde la raíz:

```bash
python frontend/tests/dashboard_browser_smoke.py
```

Reutiliza Playwright y las variables opcionales descritas en la prueba de la mesa.
Comprueba KPI contra el GET real, filtros, carga multipart, navegación con OCS,
temas, móvil y conservación del cálculo anterior si falla una actualización.


## Consistencia de salud y presentación

La mesa OCS y el tablero consumen `estado_salud` calculado por el backend con
FEFO a 14 días. La mesa ya no obtiene su contador desde los avisos de lead time:
esos avisos se consultan como urgencias separadas. El cliente verifica SKU únicos
y que `salud_catalogo` coincida con las filas; requiere actualizar ambos servicios.
Los productos descontinuados conservan su estado de salud visible aunque la
compra esté bloqueada, para que los badges no oculten riesgos contados.

Cobertura se presenta con un decimal máximo (615.3 d). El tooltip conserva la
precisión original; los filtros usan el estado recibido, sin recalcular desde
el texto redondeado. El pronóstico muestra en su tooltip la fórmula de pesos y
las fechas exactas de su ventana, tomadas de `auditoria_demanda`.

Los importes editados usan `lib/money.ts`: unidades por costo decimal del catálogo
y redondeo HALF_UP a centavos, igual que el XLSX del servidor. Una respuesta con
costos incompatibles con esa fórmula se rechaza antes de mostrar la mesa.


Las fuentes y la ventana se comparten mediante `components/dataset-provider.tsx`,
montado en el layout raíz. Ambas vistas recalculan desde esa misma selección.
El indicador de fuentes permite distinguir archivos cargados y archivos del
servicio. Los documentos no se escriben en localStorage ni en el servidor.
Para comprobarlo con copias temporales diferentes de los originales:

```bash
python frontend/tests/dataset_browser_smoke.py
```
