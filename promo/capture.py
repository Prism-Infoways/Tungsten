"""Retake the screenshots in promo/shots/ from the shop demo.

    python -m examples.shop.seed
    uvicorn examples.shop.app:app --port 8000 &
    python promo/capture.py               # all shots
    python promo/capture.py products form # just these

Shots are 1600x1000 at 1.5x (2400x1500 pixels). website/build.py turns them into the site's webp images.
"""
import argparse, asyncio, pathlib, sqlite3
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).parent
DB = HERE.parent / "shop.db"
BASE = "http://127.0.0.1:8000/admin"


async def settle(page):
    await page.wait_for_load_state("networkidle")
    await page.evaluate("document.fonts.ready")
    await page.wait_for_timeout(700)  # let charts and transitions finish


async def search(page):
    await page.goto(BASE)
    await page.fill("input[name=q]", "smart")
    await page.wait_for_selector("#tw-search-results a")


async def query_builder(page):
    await page.goto(BASE + "/products")
    await page.wait_for_load_state("networkidle")
    await page.get_by_role("button", name="More filters").click()
    await page.wait_for_timeout(400)
    await page.get_by_role("button", name="Add rule").click()
    await page.wait_for_timeout(400)
    await page.get_by_role("button", name="Price", exact=True).last.click()
    await page.wait_for_load_state("networkidle")
    await page.locator("select[name$='.op']").first.select_option(label="Is greater than")
    await page.wait_for_load_state("networkidle")
    value = page.locator("input[name$='.v']").first
    await value.fill("3000")
    await value.press("Tab")
    await page.wait_for_load_state("networkidle")
    await page.get_by_role("button", name="Add rule").last.click()
    await page.wait_for_timeout(400)
    await page.get_by_role("button", name="Featured", exact=True).last.click()
    await page.wait_for_load_state("networkidle")
    await page.evaluate("window.scrollTo(0, 330)")


def set_verified(verified: bool):
    with sqlite3.connect(DB) as c:
        c.execute("update users set email_verified_at = " + ("datetime('now', '-400 days')" if verified else "NULL")
                  + " where email = 'admin@example.com'")


SHOTS = {
    # name: (url or callable, theme, locale)
    "dashboard": ("", "light", "en"),
    "dark_dashboard": ("", "dark", "en"),
    "hindi_dashboard": ("", "light", "hi"),
    "products": ("/products", "light", "en"),
    "dark_products": ("/products", "dark", "en"),
    "hindi_products": ("/products", "light", "hi"),
    "form": ("/products/1/edit", "light", "en"),
    "dark_form": ("/products/1/edit", "dark", "en"),
    "view": ("/orders/1", "light", "en"),
    "wizard": ("/users/create", "light", "en"),
    "two_factor": ("/two-factor", "light", "en"),
    "search": (search, "light", "en"),
    "query_builder": (query_builder, "light", "en"),
    "login": ("/login", "light", "en"),
    "verify": ("/email-verification/prompt", "light", "en"),
}


async def main(names):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        sessions = {}

        async def context(theme, locale, signed_in=True):
            key = (theme, locale, signed_in)
            if key not in sessions:
                ctx = await b.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1.5,
                                          extra_http_headers={"Accept-Language": locale})
                await ctx.add_init_script(f"localStorage.setItem('tw-theme', '{theme}')")
                if signed_in:
                    page = await ctx.new_page()
                    await page.goto(BASE + "/login")
                    await page.fill("input[name=email]", "admin@example.com")
                    await page.fill("input[name=password]", "password")
                    await page.press("input[name=password]", "Enter")
                    await page.wait_for_load_state("networkidle")
                    await page.close()
                sessions[key] = ctx
            return sessions[key]

        for name in names:
            target, theme, locale = SHOTS[name]
            if name == "verify":
                set_verified(False)
            try:
                ctx = await context(theme, locale, signed_in=name != "login")
                page = await ctx.new_page()
                if callable(target):
                    await target(page)
                else:
                    await page.goto(BASE + target)
                await settle(page)
                await page.screenshot(path=str(HERE / "shots" / f"{name}.png"))
                await page.close()
                print("shot", name, flush=True)
            finally:
                if name == "verify":
                    set_verified(True)
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", default=list(SHOTS))
    asyncio.run(main(ap.parse_args().names))
