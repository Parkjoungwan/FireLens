"""
서울 화재출동 현황 전처리
- 2021~2024 CSV 합치기
- 좌표(LON/LAT) → 행정동 매핑 (행정동 GeoJSON spatial join)
- 행정동별 연도별 화재건수, 인명피해, 재산피해 집계
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import os

RAW = "data/raw/fire_seoul"
SHP = "data/raw/shp/hangjeongdong_seoul.geojson"
OUT = "data/processed/fire_seoul_dong.csv"

os.makedirs("data/processed", exist_ok=True)

YEARS = [2021, 2022, 2023, 2024]

COLS_USE = [
    "WRINV_NO",         # 화재고유번호
    "DTH_CNT",          # 사망자수
    "INJPSN_CNT",       # 부상자수
    "HNL_DAM_CNT",      # 이재민수
    "PRPT_DAM_AMT",     # 재산피해액
    "OCRN_YR",          # 발생연도
    "OCRN_YMD",         # 발생일
    "DAMG_RGN_LOT",     # 경도
    "DAMG_RGN_LAT",     # 위도
    "GRNDS_CTPV_NM",    # 시도
    "GRNDS_SGG_NM",     # 시군구
    "FCLT_PLC_LCLSF_NM", # 장소대분류
]

def load_fire():
    dfs = []
    for yr in YEARS:
        path = os.path.join(RAW, f"fire_seoul_{yr}.csv")
        df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        df["year"] = yr
        # 필요 컬럼만 (없는 컬럼 무시)
        cols = [c for c in COLS_USE if c in df.columns] + ["year"]
        dfs.append(df[cols])
    return pd.concat(dfs, ignore_index=True)

def spatial_join_dong(df, shp_path):
    # 좌표 유효한 행만
    df = df.dropna(subset=["DAMG_RGN_LOT", "DAMG_RGN_LAT"]).copy()
    df = df[(df["DAMG_RGN_LOT"] > 120) & (df["DAMG_RGN_LOT"] < 132)]
    df = df[(df["DAMG_RGN_LAT"] > 33) & (df["DAMG_RGN_LAT"] < 39)]

    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(lon, lat) for lon, lat in zip(df["DAMG_RGN_LOT"], df["DAMG_RGN_LAT"])],
        crs="EPSG:4326"
    )

    dong = gpd.read_file(shp_path)
    if dong.crs is None:
        dong = dong.set_crs("EPSG:4326")
    else:
        dong = dong.to_crs("EPSG:4326")

    joined = gpd.sjoin(gdf, dong[["adm_cd", "adm_nm", "geometry"]], how="left", predicate="within")
    return joined

def aggregate(joined):
    agg = (
        joined.groupby(["adm_cd", "adm_nm", "year"])
        .agg(
            fire_count=("WRINV_NO", "count"),
            death_cnt=("DTH_CNT", "sum"),
            injury_cnt=("INJPSN_CNT", "sum"),
            property_damage=("PRPT_DAM_AMT", "sum"),
        )
        .reset_index()
    )
    return agg

def main():
    print("화재 데이터 로드...")
    df = load_fire()
    print(f"  총 {len(df):,}건")

    print("공간 조인 (행정동 매핑)...")
    joined = spatial_join_dong(df, SHP)
    matched = joined["adm_cd"].notna().sum()
    print(f"  매핑 성공: {matched:,} / {len(joined):,}")

    print("행정동별 집계...")
    agg = aggregate(joined)
    print(f"  행정동×연도 조합: {len(agg):,}")

    agg.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}")
    print(agg.head())

if __name__ == "__main__":
    main()
