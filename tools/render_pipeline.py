"""파이프라인 다이어그램 → PNG (고해상도)"""
from playwright.sync_api import sync_playwright
from pathlib import Path

OUT = Path("data/processed/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
html = (Path(__file__).parent / "pipeline_diagram.html").resolve().as_uri()

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
    page.goto(html, wait_until="networkidle")
    page.wait_for_timeout(1500)  # 폰트 로드
    page.locator("#slide").screenshot(path=str(OUT / "07_data_pipeline.png"))
    browser.close()

pth = OUT / "07_data_pipeline.png"
print("저장:", pth.resolve(), f"({pth.stat().st_size//1024}KB)")
