"""
행정동 경계 GeoJSON 다운로드 (vuski/admdongkor GitHub)
서울특별시 행정동만 필터링해서 저장
"""
import urllib.request
import json
import os

RAW_SHP_DIR = "data/raw/shp"
os.makedirs(RAW_SHP_DIR, exist_ok=True)

# vuski/admdongkor - 전국 행정동 GeoJSON
URLS = [
    "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20230101/HangJeongDong_ver20230101.geojson",
    "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20220101/HangJeongDong_ver20220101.geojson",
]
# raqoon886 - 서울 전용 (폴백)
URL_SEOUL_ONLY = "https://raw.githubusercontent.com/raqoon886/Local_HangJeongDong/master/hangjeongdong_%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C.geojson"

OUT_ALL = os.path.join(RAW_SHP_DIR, "hangjeongdong_all.geojson")
OUT_SEOUL = os.path.join(RAW_SHP_DIR, "hangjeongdong_seoul.geojson")

def try_download(urls):
    for url in urls:
        try:
            print(f"시도: {url}")
            urllib.request.urlretrieve(url, OUT_ALL)
            print(f"성공: {OUT_ALL}")
            return True
        except Exception as e:
            print(f"  실패: {e}")
    return False

def normalize_properties(feat):
    """
    vuski admdongkor 속성 정규화
    adm_cd2 (10자리) → adm_cd 로 통일
    """
    props = feat["properties"]
    # vuski: adm_cd2 = 10자리 행정동코드, adm_cd = 7자리 (사용 안 함)
    cd = props.get("adm_cd2") or props.get("adm_cd") or ""
    nm = props.get("adm_nm", "")
    sido = props.get("sido", "")
    feat["properties"]["adm_cd"] = str(cd).zfill(10) if cd else ""
    feat["properties"]["adm_nm"] = nm
    feat["properties"]["sido"] = sido
    return feat

def download():
    if not os.path.exists(OUT_SEOUL):
        if os.path.exists(OUT_ALL):
            print(f"전국 파일 존재: {OUT_ALL}")
        else:
            ok = try_download(URLS)
            if not ok:
                # 서울 전용 폴백
                print("전국 다운로드 실패 → 서울 전용으로 대체")
                urllib.request.urlretrieve(URL_SEOUL_ONLY, OUT_SEOUL)
                print(f"서울 GeoJSON 저장: {OUT_SEOUL}")
                with open(OUT_SEOUL, encoding="utf-8") as f:
                    geojson = json.load(f)
                geojson["features"] = [normalize_properties(f) for f in geojson["features"]]
                with open(OUT_SEOUL, "w", encoding="utf-8") as f:
                    json.dump(geojson, f, ensure_ascii=False)
                if geojson["features"]:
                    print("속성 키:", list(geojson["features"][0]["properties"].keys()))
                return

    if os.path.exists(OUT_ALL):
        with open(OUT_ALL, encoding="utf-8") as f:
            geojson = json.load(f)
        total = len(geojson["features"])
        print(f"전국 행정동 수: {total}")

        # 서울 필터 (sido == '11')
        geojson["features"] = [normalize_properties(f) for f in geojson["features"]]
        seoul = [
            feat for feat in geojson["features"]
            if feat["properties"].get("sido") == "11"
        ]
        print(f"서울 행정동 수: {len(seoul)}")
        seoul_geojson = {"type": "FeatureCollection", "features": seoul}
        with open(OUT_SEOUL, "w", encoding="utf-8") as f:
            json.dump(seoul_geojson, f, ensure_ascii=False)
        print(f"저장: {OUT_SEOUL}")

    with open(OUT_SEOUL, encoding="utf-8") as f:
        s = json.load(f)
    if s["features"]:
        print("속성 키:", list(s["features"][0]["properties"].keys()))
        print(f"서울 행정동 최종: {len(s['features'])}개")

if __name__ == "__main__":
    download()
