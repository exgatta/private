# -*- coding: utf-8 -*-
"""溢れセルを実測し、縮小クラスを段階的に適用して全セルを収める"""
import asyncio, json, subprocess, sys
from playwright.async_api import async_playwright

BASE = "/tmp/claude-0/-home-user-gmail-manager/eb1b9397-4683-592b-9396-426fb1eb64d7/scratchpad"
STEPS = ["", "sm", "xs", "xxs"]
rows = json.load(open(f"{BASE}/data/final.json"))

async def measure():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await b.new_page(viewport={"width": 2245, "height": 3179})
        await page.goto(f"file://{BASE}/poster.html")
        await page.wait_for_timeout(900)
        info = await page.evaluate("""() =>
          [...document.querySelectorAll('.grid .cell')].map((c,i) => ({
            i: i+1, over: c.scrollHeight - c.clientHeight,
            cls: c.className.replace('cell','').trim()
          })).filter(x => x.over > 1)""")
        await b.close()
    return info

for it in range(6):
    subprocess.run([sys.executable, f"{BASE}/build_poster.py"], check=True)
    bad = asyncio.run(measure())
    if not bad:
        print(f"iteration {it}: all cells fit")
        break
    try:
        ovr = json.load(open(f"{BASE}/data/size_overrides.json"))
    except FileNotFoundError:
        ovr = {}
    for x in bad:
        k = rows[x["i"] - 1]["kanji"]
        cur = x["cls"] if x["cls"] in STEPS else ""
        nxt = STEPS[min(STEPS.index(cur) + 1, len(STEPS) - 1)]
        if nxt == cur:
            print(f"WARN {k} already at xxs, still over {x['over']}px")
        ovr[k] = nxt
        print(f"iter{it}: {k} {cur or 'base'} -> {nxt} (over {x['over']}px)")
    json.dump(ovr, open(f"{BASE}/data/size_overrides.json", "w"), ensure_ascii=False)
else:
    sys.exit("did not converge")
