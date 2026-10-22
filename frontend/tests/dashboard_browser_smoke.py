"""Navegador real para el tablero; ambos servidores y Excel locales requeridos."""

import os
import re
from pathlib import Path
import shutil
import tempfile

from playwright.sync_api import expect, sync_playwright


def run():
    root = Path(__file__).resolve().parents[2]
    output = Path(os.getenv("BROWSER_OUTPUT_DIR", str(Path(tempfile.gettempdir()) / "ocs-dashboard-check")))
    output.mkdir(parents=True, exist_ok=True)
    chromium = os.getenv("CHROMIUM_PATH") or shutil.which("chromium")
    with sync_playwright() as playwright:
        options = {"headless": True}
        if chromium:
            options["executable_path"] = chromium
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            with page.expect_response(lambda response: "/api/dashboard?" in response.url, timeout=60000) as received:
                page.goto(os.getenv("FRONTEND_URL", "http://127.0.0.1:3000") + "/dashboard")
            data = received.value.json()
            assert data["estado"] == "exito", data
            expect(page.get_by_text("Datos validados", exact=True)).to_be_visible()
            keys = ["capital_sobreinventario_usd", "venta_riesgo_quiebre_usd", "inventario_riesgo_vencimiento_usd"]
            assert page.locator(".executive-kpi-value").all_text_contents() == [f"${data[key]:,.2f}" for key in keys]
            assert sum(data["salud_catalogo"].values()) == data["total_skus"]
            page.screenshot(path=str(output / "dashboard-desktop.png"), full_page=True)

            page.locator(".health-legend button").nth(0).click()
            assert all(value == "Quiebre / riesgo" for value in page.locator("tbody .health-state-pill").all_text_contents())
            show_all = page.locator(".priorities-panel .executive-panel-heading").get_by_role("button", name="Ver catálogo completo", exact=True)
            show_all.click()
            for text in page.locator("tbody tr td:nth-child(4)").all_text_contents():
                if text.endswith(" d"):
                    assert re.fullmatch(r"[\d,]+(?:\.\d)? d", text), text
            cell = next(cell for cell in data["matriz_abc"] if cell["cantidad"] > 0)
            page.get_by_role("button", name=f"Volumen {cell['volumen']}, margen {cell['margen']}: {cell['cantidad']} SKU", exact=True).click()
            expect(page.locator("tbody tr")).to_have_count(min(10, cell["cantidad"]))
            assert all(value.replace(" ", "") == f"{cell['volumen']}/{cell['margen']}" for value in page.locator("tbody .matrix-class-label").all_text_contents())
            first_sku = page.locator("tbody .sku-code").first.inner_text()
            page.get_by_label("Buscar en el detalle del tablero").fill(first_sku)
            expect(page.locator("tbody tr")).to_have_count(1)
            show_all.click()
            page.locator(".executive-kpis button").nth(2).click()
            if data[keys[2]] == 0:
                expect(page.locator("tbody tr")).to_have_count(0)
                expect(page.get_by_text("No se identificó exposición en este indicador con los criterios del corte.")).to_be_visible()
            page.get_by_role("button", name="Ver criterios", exact=False).click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.get_by_text("Margen bruto estimado", exact=True)).to_be_visible()
            page.keyboard.press("Escape")
            page.locator(".executive-kpis button").nth(0).click()
            print("PASS: GET real, KPI exactos, salud, filtros ABC/búsqueda, cero exposición y metodología", flush=True)

            page.get_by_role("button", name="Cargar archivos", exact=True).click()
            for name in ["ventas_historicas", "catalogo_sku", "inventario_actual"]:
                page.locator("#" + name).set_input_files(str(root / f"{name}.xlsx"))
            with page.expect_response(lambda response: "/api/dashboard?" in response.url and response.request.method == "POST", timeout=60000) as uploaded:
                page.get_by_role("button", name="Actualizar tablero", exact=True).click()
            assert uploaded.value.json()[keys[0]] == data[keys[0]]
            expect(page.get_by_text("Datos validados", exact=True)).to_be_visible()
            page.get_by_role("button", name="Activar modo oscuro").click()
            expect(page.locator("html")).to_have_class("dark")
            page.screenshot(path=str(output / "dashboard-dark.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
            page.get_by_role("link", name="Mesa de compras", exact=True).click()
            expect(page.get_by_text("Datos validados", exact=True)).to_be_visible(timeout=60000)
            expect(page.locator("h1")).to_contain_text("Mesa de trabajo")
            expect(page.locator("html")).to_have_class("dark")
            page.get_by_role("link", name="Tablero ejecutivo", exact=True).click()
            expect(page.get_by_text("Datos validados", exact=True)).to_be_visible(timeout=60000)
            expect(page.locator("h1")).to_contain_text("Capital")
            print("PASS: uploads reales, tema persistente, móvil y navegación de ida/vuelta con OCS", flush=True)

            page.route("**/api/dashboard?*", lambda route: route.fulfill(status=502, content_type="application/json", body='{"errores":[{"mensaje":"Servicio ejecutivo no disponible"}]}'))
            page.get_by_role("button", name="Actualizar indicadores", exact=True).click()
            expect(page.get_by_role("alert").filter(has_text="Servicio ejecutivo no disponible")).to_be_visible()
            expect(page.get_by_text("Los valores visibles corresponden al cálculo anterior; revisa el corte antes de usarlos.")).to_be_visible()
            assert page.locator(".executive-kpi-value").all_text_contents() == [f"${data[key]:,.2f}" for key in keys]
            assert not errors, errors
            print("PASS: error de conexión conserva datos con aviso; sin errores JavaScript", flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    run()
