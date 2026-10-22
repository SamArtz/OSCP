/** Proxy de destino fijo: el navegador no necesita conocer ni configurar CORS. */
export async function forward(request: Request, path: string) {
  try {
    const base = process.env.FASTAPI_URL || "http://127.0.0.1:8000";
    const destination = new URL(path, base.endsWith("/") ? base : `${base}/`);
    if (!["http:", "https:"].includes(destination.protocol)) throw new Error("Invalid protocol");
    const response = await fetch(destination, {
      method: request.method === "GET" ? "GET" : "POST",
      ...(request.method === "GET" ? {} : { body: await request.formData() }),
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(120_000)]),
    });
    const headers = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["Content-Type", "Content-Disposition"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return Response.json({ estado: "error", errores: [{ mensaje: "No se pudo conectar con el servicio de compras. Verifica que FastAPI esté iniciado y vuelve a intentar." }] }, { status: 502 });
  }
}
