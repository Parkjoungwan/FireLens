"""
FireMap FastAPI 백엔드

엔드포인트:
  GET  /api/geojson          - 위험지수 포함 GeoJSON
  GET  /api/risk             - 전체 위험지수 테이블
  GET  /api/dong/{adm_cd}    - 단일 행정동 상세
  POST /api/analyze/{adm_cd} - Vision 분석 + LLM 리포트 (온디맨드)
"""
import math, time, base64, json
import requests as req
from pathlib import Path
from io import BytesIO

import pandas as pd
import geopandas as gpd
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image

# ── 경로 ──────────────────────────────────────────────────────
BASE      = Path(__file__).parent.parent
RISK_PATH = BASE / "data/processed/risk_index_final.csv"
GEO_PATH  = BASE / "data/raw/shp/hangjeongdong_seoul.geojson"
HS_PATH   = BASE / "data/processed/hotspots.csv"
IMG_DIR   = BASE / "data/raw/satellite_images"
ANT_KEY   = open(BASE / "data/keys/anthropic_api_key.txt").read().strip()

IMG_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = BASE / "data/processed/vision_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── 데이터 로드 (앱 시작 시 1회) ─────────────────────────────
risk_df = pd.read_csv(RISK_PATH, dtype={"adm_cd": str})
risk_df["adm_cd"] = risk_df["adm_cd"].str.zfill(10)

hotspots_df = pd.read_csv(HS_PATH, dtype={"adm_cd": str})
hotspots_df["adm_cd"] = hotspots_df["adm_cd"].str.zfill(10)

gdf = gpd.read_file(GEO_PATH)
gdf["adm_cd"] = gdf["adm_cd"].astype(str).str.zfill(10)
gdf = gdf.merge(
    risk_df[["adm_cd", "risk_index", "risk_grade", "risk_class",
             "fire_rate_per_10k", "ratio_65plus", "cntr_dist_avg",
             "old_bldg_ratio", "fire_count", "avg_living_pop",
             "pct_fire_rate_per_10k", "pct_ratio_65plus",
             "pct_cntr_dist_avg", "pct_old_bldg_ratio", "pct_damage_per_fire"]],
    on="adm_cd", how="left"
)
geojson_cache = json.loads(gdf.to_json())

client = anthropic.Anthropic(api_key=ANT_KEY)

# ── ESRI 위성 이미지 ──────────────────────────────────────────
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HEADERS = {"User-Agent": "FireMap-Research/1.0"}

def lat_lon_to_tile(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    import math as m
    lat_r = m.radians(lat)
    y = int((1 - m.log(m.tan(lat_r) + 1 / m.cos(lat_r)) / m.pi) / 2 * n)
    return x, y

def fetch_satellite(lat, lon, adm_cd, rank=1) -> Path | None:
    save_path = IMG_DIR / f"{adm_cd}_{rank}.png"
    if save_path.exists() and save_path.stat().st_size > 5000:
        return save_path
    ZOOM, GRID = 18, 3
    cx, cy = lat_lon_to_tile(lat, lon, ZOOM)
    canvas = Image.new("RGB", (256 * GRID, 256 * GRID))
    for row in range(GRID):
        for col in range(GRID):
            url = ESRI.format(z=ZOOM, y=cy - 1 + row, x=cx - 1 + col)
            r = req.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                return None
            canvas.paste(Image.open(BytesIO(r.content)), (col * 256, row * 256))
            time.sleep(0.03)
    canvas.save(save_path, "PNG")
    return save_path

VISION_PROMPT = """이 이미지는 서울의 특정 지역 위성 사진입니다.
화재 안전 관점에서 분석 후 JSON만 응답하세요.

{
  "building_deterioration": <1-10>,
  "alley_width": "<wide|narrow|very_narrow>",
  "building_density": <1-10>,
  "fire_risk_score": <1-10>,
  "key_observations": "<한 줄 한국어>"
}

building_deterioration: 1=신축, 10=매우 노후(슬레이트·무허가)
alley_width: wide=소방차 가능, narrow=어려움, very_narrow=불가
fire_risk_score: 종합 구조 위험 (1=안전, 10=최고위험)
JSON만 출력."""

def run_vision(img_path: Path) -> dict:
    img_data = base64.standard_b64encode(img_path.read_bytes()).decode("utf-8")
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_data}},
            {"type": "text", "text": VISION_PROMPT},
        ]}]
    )
    raw = msg.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1].replace("json", "").strip()
    return json.loads(raw)

REPORT_PROMPT = """당신은 소방 안전 전문가입니다.
아래 데이터를 바탕으로 이 행정동의 화재 위험 분석 리포트를 3-4문장으로 작성하세요.
마지막에 핵심 권고사항 1줄을 추가하세요. 한국어로만 작성.

행정동: {adm_nm}
종합 위험지수: {risk_index}/100 ({risk_class})
화재율(1만명당): {fire_rate:.2f}건
65세+ 비율: {ratio_65:.1%}
119센터 거리: {cntr_dist:.2f}km
노후건물 비율: {old_bldg:.1%}

AI 위성 분석:
- 건물 노후도: {vision_det}/10
- 골목 폭: {vision_alley}
- 건물 밀집도: {vision_density}/10
- AI 위험점수: {vision_risk}/10
- 관찰: {vision_obs}"""

def generate_report(row: dict, vision: dict) -> str:
    prompt = REPORT_PROMPT.format(
        adm_nm      = row.get("adm_nm", ""),
        risk_index  = row.get("risk_index", 0),
        risk_class  = row.get("risk_class", ""),
        fire_rate   = float(row.get("fire_rate_per_10k") or 0),
        ratio_65    = float(row.get("ratio_65plus") or 0),
        cntr_dist   = float(row.get("cntr_dist_avg") or 0),
        old_bldg    = float(row.get("old_bldg_ratio") or 0),
        vision_det  = vision.get("building_deterioration", "N/A"),
        vision_alley= vision.get("alley_width", "N/A"),
        vision_density= vision.get("building_density", "N/A"),
        vision_risk = vision.get("fire_risk_score", "N/A"),
        vision_obs  = vision.get("key_observations", ""),
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


# ── FastAPI ───────────────────────────────────────────────────
app = FastAPI(title="FireMap API")

@app.get("/api/geojson")
def get_geojson():
    return JSONResponse(geojson_cache)

@app.get("/api/risk")
def get_risk():
    return JSONResponse(risk_df.to_dict(orient="records"))

@app.get("/api/dong/{adm_cd}")
def get_dong(adm_cd: str):
    adm_cd = adm_cd.zfill(10)
    row = risk_df[risk_df["adm_cd"] == adm_cd]
    if row.empty:
        raise HTTPException(404, "행정동 없음")
    return JSONResponse(row.iloc[0].to_dict())

@app.post("/api/analyze/{adm_cd}")
def analyze_dong(adm_cd: str):
    adm_cd = adm_cd.zfill(10)

    # 캐시 확인
    cache_path = CACHE_DIR / f"{adm_cd}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        cached["cached"] = True
        return JSONResponse(cached)

    # 행정동 데이터
    row = risk_df[risk_df["adm_cd"] == adm_cd]
    if row.empty:
        raise HTTPException(404, "행정동 없음")
    row_dict = row.iloc[0].to_dict()

    # 핫스팟 좌표 (rank=1) — 없으면 행정동 centroid 폴백
    hs = hotspots_df[(hotspots_df["adm_cd"] == adm_cd) & (hotspots_df["hotspot_rank"] == 1)]
    if not hs.empty:
        lat, lon = float(hs.iloc[0]["lat"]), float(hs.iloc[0]["lon"])
    else:
        dong_geom = gdf[gdf["adm_cd"] == adm_cd]
        if dong_geom.empty:
            raise HTTPException(404, "행정동 경계 없음")
        centroid = dong_geom.geometry.iloc[0].centroid
        lat, lon = centroid.y, centroid.x

    # 위성 이미지 수집
    img_path = fetch_satellite(lat, lon, adm_cd)
    if img_path is None:
        raise HTTPException(500, "위성 이미지 수집 실패")

    # Vision 분석
    vision = run_vision(img_path)

    # LLM 리포트
    report = generate_report(row_dict, vision)

    # 이미지 base64 (프론트 표시용)
    img_b64 = base64.standard_b64encode(img_path.read_bytes()).decode("utf-8")

    result = {
        "adm_cd":    adm_cd,
        "adm_nm":    row_dict.get("adm_nm"),
        "vision":    vision,
        "report":    report,
        "image_b64": img_b64,
        "hotspot":   {"lat": lat, "lon": lon},
        "cached":    False,
    }

    # 캐시 저장 (image_b64 제외 — 파일 크기 절약)
    cache_data = {k: v for k, v in result.items() if k != "image_b64"}
    cache_data["image_b64"] = img_b64  # 이미지도 저장 (재호출 시 API 비용 절약)
    cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")

    return JSONResponse(result)

# 정적 파일 + SPA
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
