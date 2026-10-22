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
recalcular descarta los ajustes. Se pide confirmación antes de recalcular si hay
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
