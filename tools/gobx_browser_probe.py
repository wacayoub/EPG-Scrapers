#!/usr/bin/env python3
from __future__ import annotations
import asyncio, json, re
from pathlib import Path
from playwright.async_api import async_playwright

TARGETS=[
 ("gobx-en","https://www.gobx.com/en/whats-on"),
 ("gobx-ar","https://www.gobx.com/ar/whats-on"),
 ("gobox-en","https://www.gobox.com/en/whats-on"),
]
KEY=re.compile(r"(epg|schedule|guide|programme|program|channel|listing|whats.?on|content)",re.I)

async def one(name,url,browser):
    ctx=await browser.new_context(
      locale="en-US", timezone_id="Asia/Riyadh",
      viewport={"width":1365,"height":900},
      user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    )
    page=await ctx.new_page()
    network=[]
    async def on_response(resp):
        try:
            ct=(resp.headers.get("content-type") or "").lower()
            interesting=bool(KEY.search(resp.url) or "json" in ct)
            if not interesting:
                return
            row={"url":resp.url,"status":resp.status,"content_type":ct}
            if "json" in ct and resp.status==200:
                try:
                    txt=await resp.text()
                    row["sample"]=re.sub(r"\s+"," ",txt[:1200]).strip()
                    row["bytes_estimate"]=len(txt.encode("utf-8","ignore"))
                except Exception:
                    pass
            network.append(row)
        except Exception:
            pass
    page.on("response",on_response)
    out={"name":name,"requested_url":url,"network":[]}
    try:
        resp=await page.goto(url,wait_until="domcontentloaded",timeout=45000)
        out["main_status"]=resp.status if resp else None
        await page.wait_for_timeout(12000)
        for y in (600,1200,1800):
            await page.evaluate(f"window.scrollTo(0,{y})")
            await page.wait_for_timeout(1200)
        body=(await page.locator("body").inner_text(timeout=10000))[:60000]
        out["title"]=await page.title()
        out["final_url"]=page.url
        out["body_sample"]=body[:10000]
        out["contains_times"]=bool(re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b",body,re.I))
        out["network"]=network[:300]
    except Exception as e:
        out["error"]=str(e)[:600]
        out["final_url"]=page.url
        out["network"]=network[:300]
    await ctx.close()
    return out

async def main():
    Path("reports").mkdir(exist_ok=True)
    rows=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        for i,(name,url) in enumerate(TARGETS):
            row=await one(name,url,browser)
            rows.append(row)
            print(json.dumps({
                "name":name,"main_status":row.get("main_status"),"final_url":row.get("final_url"),
                "network_matches":len(row.get("network",[])),"contains_times":row.get("contains_times"),
                "error":row.get("error")
            },ensure_ascii=False))
            if i+1<len(TARGETS):
                await asyncio.sleep(10)
        await browser.close()
    Path("reports/gobx-browser-probe.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
