"""
화재 핫스팟 탐지 — 최우선 대응 행정동 내 반복 발생 위치 추출

입력:
  data/raw/fire_seoul/fire_seoul_2021~2023.csv  (좌표 포함)
  data/processed/risk_index_final.csv           (risk_class)

출력:
  data/processed/hotspots.csv
  - adm_cd, adm_nm, risk_class
  - lat, lon        : 핫스팟 중심 좌표
  - fire_count      : 반경 내 화재 건수
  - hotspot_rank    : 행정동 내 순위 (1=가장 밀집)
"""
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.cluster import DBSCAN

RAW_DIR   = Path("data/raw/fire_seoul")
RISK_PATH = Path("data/processed/risk_index_final.csv")
OUT_PATH  = Path("data/processed/hotspots.csv")

YEARS           = [2021, 2022, 2023]
TARGET_CLASSES  = ["최우선 대응", "잠재 위험"]  # 분석 대상
HOTSPOTS_PER_DONG = 3   # 행정동당 최대 핫스팟 수
DBSCAN_EPS_KM   = 0.15  # 150m 반경
DBSCAN_MIN_PTS  = 2     # 최소 2건 이상 클러스터


def km_to_rad(km):
    return km / 6371.0


def load_fire():
    frames = []
    for yr in YEARS:
        p = RAW_DIR / f"fire_seoul_{yr}.csv"
        df = pd.read_csv(p, encoding="utf-8", low_memory=False)
        df["year"] = yr
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["DAMG_RGN_LOT", "DAMG_RGN_LAT"])
    df = df[
        df["DAMG_RGN_LOT"].between(126.7, 127.3) &
        df["DAMG_RGN_LAT"].between(37.4, 37.72)
    ]
    return df.rename(columns={"DAMG_RGN_LOT": "lon", "DAMG_RGN_LAT": "lat"})


def dbscan_hotspots(group_df, n_top=HOTSPOTS_PER_DONG):
    coords = group_df[["lat", "lon"]].values
    coords_rad = np.radians(coords)

    db = DBSCAN(
        eps=km_to_rad(DBSCAN_EPS_KM),
        min_samples=DBSCAN_MIN_PTS,
        algorithm="ball_tree",
        metric="haversine"
    ).fit(coords_rad)

    group_df = group_df.copy()
    group_df["cluster"] = db.labels_

    hotspots = []
    # 클러스터별 중심 + 건수
    for cid in sorted(set(db.labels_)):
        if cid == -1:
            continue
        members = group_df[group_df["cluster"] == cid]
        hotspots.append({
            "lat":        members["lat"].mean(),
            "lon":        members["lon"].mean(),
            "fire_count": len(members),
        })

    # 클러스터 없으면 단순 좌표 상위 (행정동 centroid 근사)
    if not hotspots:
        hotspots.append({
            "lat":        group_df["lat"].mean(),
            "lon":        group_df["lon"].mean(),
            "fire_count": len(group_df),
        })

    hs_df = pd.DataFrame(hotspots).sort_values("fire_count", ascending=False)
    hs_df["hotspot_rank"] = range(1, len(hs_df) + 1)
    return hs_df.head(n_top)


def main():
    print("=== 화재 핫스팟 탐지 ===\n")

    risk = pd.read_csv(RISK_PATH, dtype={"adm_cd": str})
    target = risk[risk["risk_class"].isin(TARGET_CLASSES)][["adm_cd", "adm_nm", "risk_class", "risk_index"]]
    print(f"분석 대상: {len(target)}개 행정동 ({', '.join(TARGET_CLASSES)})\n")

    fire = load_fire()
    print(f"화재 데이터: {len(fire):,}건 (좌표 유효)\n")

    # adm_cd 붙이기 — fire_seoul에 없으므로 spatial join 결과 활용
    # 09_fire_dispatch에서 이미 했으므로 재활용: fire에 adm_cd spatial join
    import geopandas as gpd
    gdf_fire = gpd.GeoDataFrame(
        fire, geometry=gpd.points_from_xy(fire["lon"], fire["lat"]), crs="EPSG:4326"
    )
    gdf_dong = gpd.read_file("data/raw/shp/hangjeongdong_seoul.geojson")[["adm_cd", "geometry"]]
    gdf_dong["adm_cd"] = gdf_dong["adm_cd"].astype(str).str.zfill(10)
    gdf_dong = gdf_dong.set_crs("EPSG:4326", allow_override=True)

    joined = gpd.sjoin(gdf_fire, gdf_dong, how="left", predicate="within")
    joined = joined.dropna(subset=["adm_cd"])
    joined["adm_cd"] = joined["adm_cd"].astype(str).str.zfill(10)

    # 대상 행정동만 필터
    target_cds = set(target["adm_cd"])
    subset = joined[joined["adm_cd"].isin(target_cds)]
    print(f"대상 행정동 내 화재: {len(subset):,}건\n")

    # 행정동별 DBSCAN 핫스팟
    results = []
    for adm_cd, grp in subset.groupby("adm_cd"):
        hs = dbscan_hotspots(grp)
        hs["adm_cd"] = adm_cd
        results.append(hs)

    hotspots = pd.concat(results, ignore_index=True)
    hotspots = hotspots.merge(target, on="adm_cd", how="left")
    hotspots = hotspots.sort_values(["risk_index", "hotspot_rank"], ascending=[False, True])

    col_order = ["adm_cd", "adm_nm", "risk_class", "risk_index",
                 "hotspot_rank", "lat", "lon", "fire_count"]
    hotspots = hotspots[col_order].reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    hotspots.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"핫스팟 수: {len(hotspots)}개")
    print(f"저장: {OUT_PATH}\n")
    print("상위 20 핫스팟:")
    print(hotspots.head(20)[["adm_nm", "risk_class", "hotspot_rank", "lat", "lon", "fire_count"]].to_string(index=False))


if __name__ == "__main__":
    main()
