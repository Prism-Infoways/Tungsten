"""Take the tall screenshots for the LinkedIn design video (promo/linkedin/design.html).

    python -m examples.shop.seed && uvicorn examples.shop.app:app --port 8000 &
    (cd plugins/kanban && uvicorn example:app --port 8001 &)
    uvicorn plugins.calendar.example:app --port 8002 &
    python promo/linkedin/capture.py
"""
import asyncio, pathlib
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).parent
SITE = "https://tungsten.prisminfoways.com"

SHOTS = {
    # name: (base, path, theme, full page)
    "dashboard": ("http://127.0.0.1:8000/admin", "", "light", True),
    "dark_dashboard": ("http://127.0.0.1:8000/admin", "", "dark", True),
    "ui_kit": ("http://127.0.0.1:8000/admin", "/ui-kit", "light", True),
    "dark_ui_kit": ("http://127.0.0.1:8000/admin", "/ui-kit", "dark", True),
    "orders": ("http://127.0.0.1:8000/admin", "/orders", "light", False),
    "dark_products": ("http://127.0.0.1:8000/admin", "/products", "dark", False),
    "kanban": ("http://127.0.0.1:8001/admin", "/tasks-board", "light", False),
    "calendar": ("http://127.0.0.1:8002/admin", "/calendar", "light", False),
    "website": (SITE, "/", "light", True),
}


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for name, (base, path, theme, full) in SHOTS.items():
            ctx = await b.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1.5)
            await ctx.add_init_script(f"localStorage.setItem('tw-theme', '{theme}')")
            page = await ctx.new_page()
            if base != SITE:
                await page.goto(base + "/login")
                await page.fill("input[name=email]", "admin@example.com")
                await page.fill("input[name=password]", "password")
                await page.press("input[name=password]", "Enter")
                await page.wait_for_load_state("networkidle")
            await page.goto(base + path)
            await page.wait_for_load_state("networkidle")
            if full:  # scroll down once so scroll-in animations and lazy images run
                await page.evaluate("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) {
                    window.scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); } window.scrollTo(0, 0); }""")
            await page.evaluate("document.fonts.ready")
            await page.wait_for_timeout(1200)
            await page.screenshot(path=str(HERE / "shots" / f"{name}.png"), full_page=full)
            print("shot", name, page.url, flush=True)
            await ctx.close()
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
