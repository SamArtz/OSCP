# Revisión de los nueve Excel adjuntos

Revisión realizada sobre los archivos originales, sin modificarlos. El corte de
inventario es **21 de octubre de 2026**; las ventas van del 1 de noviembre de 2024
al 20 de octubre de 2026. Las hojas `Diccionario` se usan como documentación,
sin tratarlas como instrucciones operativas.

## Volumen

| Archivo / hoja principal | Filas |
| --- | ---: |
| ventas_historicas / Ventas | 24.222 |
| catalogo_sku / Catalogo | 50 |
| inventario_actual / Inventario | 50 |
| inventario_historico / Snapshots | 1.030 |
| ordenes_compra_historicas / ComprasHistorial | 149 |
| maestro_clientes_rutas / Clientes | 100 |
| maestro_proveedores / Proveedores | 3 |
| calendario_feriados_promociones / Calendario | 9 |
| parametros_ocs / Parametros | 4 |

No se encontraron filas completamente duplicadas en estas hojas. Las únicas
celdas vacías son OC/fecha de tránsito en 36 filas de inventario sin tránsito;
son vacíos coherentes, no datos faltantes que deban convertirse en cero.

## Hallazgos que conviene corregir

| Hallazgo | Evidencia | Acción sugerida |
| --- | --- | --- |
| EAN incorrectos | **45 de 50** códigos incumplen el dígito verificador EAN-13. Ejemplo: `7410100000000`. | Obtener códigos oficiales o confirmar que son datos ficticios. Se informa como advertencia; no se recalculan identificadores automáticamente. |
| Histórico de inventario incompleto | Solo incluye `SKU-1000` a `SKU-1009`: **10 de 50 SKU**, 103 cortes semanales del 04/11/2024 al 19/10/2026. Ninguna de sus 1.030 filas tiene stock cero. | Completar los 40 SKU restantes y, para censura diaria, aportar existencias/rupturas diarias. Una foto semanal no demuestra disponibilidad durante toda la semana. |
| Calendario fuera de la mayor parte del horizonte | Solo hay nueve feriados de **2024** y ninguna promoción. Apenas dos fechas caen dentro del período de ventas. | Incorporar feriados de 2025 y 2026 y promociones reales; no interpretar eventos ausentes como días normales confirmados. |
| Tránsito sin OC trazable en el adjunto | Las **14** filas con tránsito hacen referencia a `OC-99xx`, ninguna presente en las 149 compras históricas. Ejemplo: `OC-9901`. | Incorporar órdenes abiertas o un archivo separado de tránsito. No prueba que las OC sean inexistentes; falta su respaldo en los adjuntos. |
| Recepción real posterior al corte | `OC-2148`, SKU-1018, registra `fecha_recepcion_real=2026-10-25`, posterior al corte actual 2026-10-21. | Confirmar si es fecha estimada, fecha mal ingresada o extracción con fechas mezcladas. No usarla como recepción observada al corte. |
| Día de pedido no reconocible | PROV-002 tiene `dias_pedido=MUE`. | Confirmar si corresponde a MIE o JUE y normalizar los días válidos. No corregirlo por suposición. |
| NC sin referencia a la factura original | Hay **958 NC**, pero no existe columna de documento original/referencia. | Añadir la referencia para verificar devoluciones acumuladas, motivos y límites contra la venta original. El endpoint puede normalizar cantidades, pero no reconciliar cada devolución contra su factura. |

## Diferencias que requieren criterio de negocio

Estas comparaciones usan los maestros **actuales**; no demuestran por sí solas
que una operación histórica sea incorrecta.

- **34 de 50 SKU** tienen `lead_time_dias` diferente al `lead_time_prometido_dias`
  de su proveedor. Ejemplo: SKU-1000 tiene 30 días y PROV-001 promete 15.
  Puede existir una regla específica por SKU: hay que definir la precedencia para
  órdenes de compra. Los plazos reales observados van de 3 a 33 días; sus promedios
  son 21,36 días para PROV-001, 21,05 para PROV-002 y 14,96 para PROV-003.
- **19 de 149 compras** quedan por debajo del MOQ actual del SKU. Ejemplo:
  OC-2021 pidió 20 cajas de SKU-1028, cuyo MOQ actual es 30. Confirmar excepciones
  o agregar vigencia histórica de los parámetros antes de declararlas inválidas.
- **30 de 50 SKU** tienen país de origen distinto al país consignado para su
  proveedor. Un producto puede fabricarse en un país y su distribuidor operar en
  otro: aclarar qué representa `pais_origen` en cada maestro.
- SKU-1047 está marcado `LANZAMIENTO`, pero tiene 71 movimientos desde el
  04/11/2024 hasta el 17/10/2026. Confirmar si la categoría sigue siendo válida o
  agregar fecha de lanzamiento y vigencia del estado. Los dos SKU actualmente
  descontinuados tienen ventas históricas; eso por sí solo es coherente.
- `nivel_servicio_objetivo=0.95` es una probabilidad, **no** el valor Z. Cuando se
  implemente ese motor habrá que convertirla al cuantil normal correspondiente
  (aproximadamente 1,645 para una cola), sin usar 0,95 como Z directamente.

## Datos coherentes y resultados del ETL

- **23.264 facturas** y **958 notas de crédito**. Todas las NC tienen unidades e
  importe negativos; ninguna factura tiene unidades negativas. No se debe
  multiplicar indiscriminadamente las NC por -1.
- Unidades facturadas: **160.415**; devueltas: **6.384**; venta neta en unidades:
  **154.031**. Estos son movimientos observados, sin estimar demanda perdida.
- Hay **1.209 filas con bonificación**, con **2.418 unidades bonificadas** en total.
  Ninguna NC devuelve bonos en estos archivos. La salida neta algebraica incluyendo
  bonos es **156.449 unidades**; no representa recuperación automática de stock vendible.
- Venta neta monetaria: **USD 274.503,34**. Las 24.222 líneas coinciden con
  unidades vendidas × precio unitario, con tolerancia de un centavo, excluyendo
  bonificaciones. No se atribuye ingreso a las unidades gratuitas.
- Hay **8 SKU con disponible cero**: SKU-1025, SKU-1030, SKU-1035, SKU-1040,
  SKU-1042, SKU-1043, SKU-1046 y SKU-1049. Los ocho se etiquetan como posible
  demanda censurada al corte. Cuatro tienen tránsito, que no cuenta como
  disponible hoy. SKU-1049 está descontinuado: confirmar si su ruptura es deliberada.
- Todos los SKU de ventas, inventario y compras existen en el catálogo; los
  clientes de ventas y proveedores de catálogo/compras existen en sus maestros.
  No se encontraron discrepancias de canal/vendedor contra el maestro de clientes
  ni de proveedor de compra contra el proveedor del SKU.
- En las 149 compras coinciden cajas × unidades por caja y unidades × costo con
  los campos de unidades e importe. No hay recepciones anteriores a la emisión.
- El inventario actual tiene un único corte, una bodega, todos los SKU del catálogo
  y cantidades disponibles/en tránsito que respetan las unidades por caja.

## Alcance de las validaciones

El endpoint devuelve errores para esquemas, tipos, campos obligatorios, stock
negativo, SKU desconocidos, duplicados y metadatos de tránsito incompletos. Los
EAN incorrectos son advertencias. Los otros seis libros se revisaron para este
informe; no se incorporan al contrato del endpoint de este primer paso.

La falta de histórico completo y de bodega en ventas impide reconstruir períodos
de demanda censurada de forma confiable. El ETL conserva las señales observadas
y no rellena ventas perdidas, ni crea etiquetas históricas con el inventario actual.
