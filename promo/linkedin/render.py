"""Render design.html to design.mp4 (1080x1350, LinkedIn 4:5), frame by frame.

    python promo/linkedin/render.py                 # full video
    python promo/linkedin/render.py --stills 2,8,13 # a few still frames for checking
    python promo/linkedin/sound.py                 # then add the soundtrack
"""
import argparse, asyncio, pathlib, subprocess
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).parent
FPS = 30


async def main(args):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await b.new_page(viewport={"width": 1080, "height": 1350})
        await page.goto((HERE / "design.html").as_uri() + "#capture")
        await page.wait_for_load_state("networkidle")
        await page.evaluate("document.fonts.ready")
        await page.evaluate("Promise.all([...document.images].map(i => i.decode()))")
        if args.stills:
            out = pathlib.Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            for s in args.stills.split(","):
                await page.evaluate(f"render({float(s)})")
                await page.screenshot(path=str(out / f"still_{float(s):05.1f}.jpg"), type="jpeg", quality=85)
            await b.close()
            return
        duration = await page.evaluate("DURATION")
        frames = int((duration + 1) * FPS)
        ff = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
             "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(HERE / "design.mp4")], stdin=subprocess.PIPE)
        for i in range(frames):
            await page.evaluate(f"render({i / FPS})")
            ff.stdin.write(await page.screenshot(type="jpeg", quality=94))
            if i % 150 == 0:
                print(f"frame {i}/{frames}", flush=True)
        ff.stdin.close()
        ff.wait()
        await b.close()
        print("done:", HERE / "design.mp4")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills")
    ap.add_argument("--out", default=str(HERE / "stills"))
    asyncio.run(main(ap.parse_args()))
