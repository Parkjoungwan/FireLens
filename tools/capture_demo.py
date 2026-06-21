"""시연 자료 풀해상도 캡처 → data/processed/screenshots/"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import time

OUT = Path("data/processed/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:8000"
VW = {"width": 1440, "height": 900}

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport=VW, device_scale_factor=2)  # 2x 고해상도

    # ── 랜딩 ──
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(3500)  # hero 지도 타일 로드
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(500)
    page.locator(".lp-hero").screenshot(path=str(OUT / "01_landing_hero.png"))
    page.locator("#problem").screenshot(path=str(OUT / "02_landing_problem.png"))
    page.locator("#services").screenshot(path=str(OUT / "03_landing_services.png"))
    print("랜딩 3장 완료")

    # ── 대시보드 기본 ──
    page.goto(f"{BASE}/dashboard.html", wait_until="networkidle")
    page.wait_for_timeout(4000)  # 지도 타일 로드
    page.screenshot(path=str(OUT / "04_dashboard_overview.png"))
    print("대시보드 전체 완료")

    # ── 행정동 상세 (평창동, 캐시) ──
    page.evaluate("selectDong('1111056000')")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "05_dashboard_detail.png"))
    print("상세 패널 완료")

    # ── AI 위성 분석 (캐시 → 무과금) ──
    page.evaluate("confirmAnalysis()")
    # 결과 대기
    for _ in range(30):
        page.wait_for_timeout(400)
        shown = page.evaluate(
            "getComputedStyle(document.getElementById('ai-result')).display !== 'none'"
        )
        if shown:
            break
    page.wait_for_timeout(800)
    page.evaluate("document.getElementById('panel-detail').scrollTo(0, 9999)")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "06_dashboard_ai_result.png"))
    # 사이드 패널만 따로
    page.locator("#panel").screenshot(path=str(OUT / "06b_ai_panel_only.png"))
    print("AI 분석 완료")

    browser.close()

print("\n저장 위치:", OUT.resolve())
for f in sorted(OUT.glob("*.png")):
    print(" -", f.name, f"({f.stat().st_size//1024}KB)")
