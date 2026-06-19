"""
위성 이미지 수집 (ESRI World Imagery) + Claude Vision 화재 위험 분석

입력:  data/processed/hotspots.csv
출력:  data/processed/roadview_risk.csv
       data/processed/roadview_risk_dong.csv
       data/raw/satellite_images/  (PNG 이미지 캐시)

ESRI World Imagery 타일 (무료, 키 없음) 3x3 스티칭
→ Claude Vision으로 건물 노후도 / 골목 폭 / 화재 구조 위험 분석
→ 행정동별 Vision 위험 점수 집계
"""
import math
import time
import base64
import json
import requests
import pandas as pd
import anthropic
from pathlib import Path
from PIL import Image
from io import BytesIO

ANTHROPIC_KEY = open("data/keys/anthropic_api_key.txt").read().strip()

HOTSPOT_PATH = Path("data/processed/hotspots.csv")
OUT_PATH     = Path("data/processed/roadview_risk.csv")
IMG_DIR      = Path("data/raw/satellite_images")
IMG_DIR.mkdir(parents=True, exist_ok=True)

# ESRI World Imagery 타일 서버
ESRI_URL  = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
TILE_SIZE = 256
ZOOM      = 18   # 건물 단위 식별 가능 레벨
GRID      = 3    # 3×3 타일 스티칭 → 768×768 이미지

HEADERS = {"User-Agent": "FireMap-Research/1.0 (fire safety research, non-commercial)"}

VISION_PROMPT = """이 이미지는 서울의 특정 지역을 촬영한 위성 사진입니다.
화재 안전 관점에서 분석하고 아래 JSON 형식으로만 응답하세요.

{
  "building_deterioration": <1-10>,
  "alley_width": "<wide|narrow|very_narrow>",
  "building_density": <1-10>,
  "fire_risk_score": <1-10>,
  "key_observations": "<한 줄 한국어 설명>"
}

각 항목 기준:
- building_deterioration: 1=신축/양호, 10=매우 노후(슬레이트 지붕, 낡은 외벽, 무허가 건물)
- alley_width: wide=소방차 진입 가능, narrow=어려움, very_narrow=불가
- building_density: 1=저밀도, 10=초고밀도 밀집
- fire_risk_score: 위 요소 종합 (1=안전, 10=최고위험)

JSON만 출력. 다른 텍스트 없음."""


# ── 타일 좌표 계산 ────────────────────────────────────────────

def lat_lon_to_tile(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return x, y


def fetch_tile(z, y, x, retries=3) -> Image.Image | None:
    url = ESRI_URL.format(z=z, y=y, x=x)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                return Image.open(BytesIO(r.content))
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def fetch_satellite_image(lat: float, lon: float, save_path: Path) -> bool:
    if save_path.exists() and save_path.stat().st_size > 5000:
        return True

    cx, cy = lat_lon_to_tile(lat, lon, ZOOM)
    offset = GRID // 2  # 1 (3x3 기준)

    canvas = Image.new("RGB", (TILE_SIZE * GRID, TILE_SIZE * GRID))

    for row in range(GRID):
        for col in range(GRID):
            tx = cx - offset + col
            ty = cy - offset + row
            tile = fetch_tile(ZOOM, ty, tx)
            if tile is None:
                return False
            canvas.paste(tile, (col * TILE_SIZE, row * TILE_SIZE))
            time.sleep(0.05)

    canvas.save(save_path, "PNG")
    return True


# ── Claude Vision 분석 ───────────────────────────────────────

def analyze_with_vision(img_path: Path, client: anthropic.Anthropic) -> dict:
    img_data = base64.standard_b64encode(img_path.read_bytes()).decode("utf-8")

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_data,
                        }
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ]
            }]
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  JSON 파싱 실패: {e} / raw={raw[:80]}")
        return {}
    except Exception as e:
        print(f"  Vision API 실패: {e}")
        return {}


# ── 메인 ─────────────────────────────────────────────────────

def main():
    print("=== 위성 이미지 화재 위험 분석 (ESRI + Claude Vision) ===\n")

    hotspots = pd.read_csv(HOTSPOT_PATH, dtype={"adm_cd": str})
    print(f"핫스팟 수: {len(hotspots)}개\n")

    client   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    results  = []
    success  = 0
    fail_img = 0
    fail_vis = 0

    for i, row in hotspots.iterrows():
        adm_nm_short = str(row["adm_nm"]).replace("서울특별시 ", "").split(" ", 1)[-1]
        print(f"[{i+1:3d}/{len(hotspots)}] {adm_nm_short} rank={int(row['hotspot_rank'])} "
              f"({row['lat']:.4f}, {row['lon']:.4f})", end=" ")

        img_name = f"{row['adm_cd']}_{int(row['hotspot_rank'])}.png"
        img_path = IMG_DIR / img_name

        # 1. 위성 이미지 수집
        ok = fetch_satellite_image(row["lat"], row["lon"], img_path)
        if not ok:
            print("-> 이미지 실패")
            fail_img += 1
            results.append({**row.to_dict(), "vision_error": "img_fail"})
            continue

        # 2. Vision 분석
        analysis = analyze_with_vision(img_path, client)
        if not analysis:
            print("-> Vision 실패")
            fail_vis += 1
            results.append({**row.to_dict(), "vision_error": "vision_fail"})
            time.sleep(1)
            continue

        print(f"-> 노후={analysis.get('building_deterioration')} "
              f"골목={analysis.get('alley_width')} "
              f"위험={analysis.get('fire_risk_score')} "
              f"| {analysis.get('key_observations','')[:40]}")

        results.append({
            **row.to_dict(),
            "vision_deterioration": analysis.get("building_deterioration"),
            "vision_alley_width":   analysis.get("alley_width"),
            "vision_density":       analysis.get("building_density"),
            "vision_fire_risk":     analysis.get("fire_risk_score"),
            "vision_observations":  analysis.get("key_observations"),
            "vision_error":         None,
        })
        success += 1
        time.sleep(0.5)

    print(f"\n완료: 성공={success} 이미지실패={fail_img} Vision실패={fail_vis}")

    df = pd.DataFrame(results)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    # 행정동별 집계
    valid = df[df["vision_error"].isna()].copy()
    if len(valid) > 0:
        dong_agg = (
            valid.groupby(["adm_cd", "adm_nm", "risk_class"])
            .agg(
                vision_risk_avg          =("vision_fire_risk",      "mean"),
                vision_deterioration_avg =("vision_deterioration",  "mean"),
                vision_alley_narrow_ratio=(
                    "vision_alley_width",
                    lambda x: (x.isin(["narrow", "very_narrow"])).mean()
                ),
                vision_samples           =("vision_fire_risk",      "count"),
            )
            .reset_index()
        )
        dong_agg["vision_risk_avg"]         = dong_agg["vision_risk_avg"].round(2)
        dong_agg["vision_deterioration_avg"]= dong_agg["vision_deterioration_avg"].round(2)
        dong_agg["vision_alley_narrow_ratio"]= dong_agg["vision_alley_narrow_ratio"].round(2)

        out_dong = OUT_PATH.parent / "roadview_risk_dong.csv"
        dong_agg.sort_values("vision_risk_avg", ascending=False).to_csv(
            out_dong, index=False, encoding="utf-8-sig"
        )

        print(f"\n행정동별 Vision 집계: {len(dong_agg)}개")
        print(dong_agg.sort_values("vision_risk_avg", ascending=False)
              .head(15)[["adm_nm", "vision_risk_avg", "vision_deterioration_avg",
                          "vision_alley_narrow_ratio", "vision_samples"]]
              .to_string(index=False))
        print(f"\n저장: {out_dong}")

    print(f"저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
