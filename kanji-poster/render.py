import asyncio, sys
from playwright.async_api import async_playwright

BASE = "/tmp/claude-0/-home-user-gmail-manager/eb1b9397-4683-592b-9396-426fb1eb64d7/scratchpad"

async def main():
    png_only = "--png" in sys.argv
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await b.new_page(viewport={"width": 2245, "height": 3179})
        await page.goto(f"file://{BASE}/poster.html")
        await page.wait_for_timeout(1500)
        # 中央付近セルの overflow チェック
        overflow = await page.evaluate("""() => {
            const bad = [];
            document.querySelectorAll('.cell').forEach((c,i) => {
                if (c.scrollHeight > c.clientHeight + 1 || c.scrollWidth > c.clientWidth + 1)
                    bad.push(i+1);
            });
            return bad;
        }""")
        print("overflowing cells:", overflow if overflow else "none")
        await page.screenshot(path=f"{BASE}/preview_full.png", full_page=True)
        # 拡大プレビュー（左上部分）
        await page.screenshot(path=f"{BASE}/preview_zoom.png",
                              clip={"x": 0, "y": 0, "width": 1400, "height": 1100})
        await page.screenshot(path=f"{BASE}/preview_zoom2.png",
                              clip={"x": 45, "y": 700, "width": 900, "height": 700})
        if not png_only:
            await page.pdf(path=f"{BASE}/kanji_grade2_A1.pdf",
                           prefer_css_page_size=True, print_background=True)
            print("pdf written")
        await b.close()

asyncio.run(main())
