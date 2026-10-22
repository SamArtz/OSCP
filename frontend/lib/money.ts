/** Unidades × precio decimal del catálogo, ROUND_HALF_UP a centavos como Python.
 * BigInt evita que 1.005 se convierta en 1.00 por el float binario de JavaScript.
 */
export function lineCostCents(units: number, unitCost: number): number {
  if (!Number.isSafeInteger(units) || units < 0 || !Number.isFinite(unitCost) || unitCost < 0) {
    throw new Error("Cantidad o costo unitario inválido.");
  }
  const [coefficient, exponent = "0"] = unitCost.toString().toLowerCase().split("e");
  const [whole, fraction = ""] = coefficient.split(".");
  const scale = fraction.length - Number(exponent);
  const numerator = BigInt(whole + fraction) * BigInt(units);
  const cents = scale <= 2
    ? numerator * 10n ** BigInt(2 - scale)
    : (numerator * 100n + (10n ** BigInt(scale)) / 2n) / (10n ** BigInt(scale));
  const result = Number(cents);
  if (!Number.isSafeInteger(result)) throw new Error("El importe excede la precisión monetaria admitida.");
  return result;
}

export const lineCost = (units: number, unitCost: number) => lineCostCents(units, unitCost) / 100;
