"""
화재 출동 데이터 전처리 → 행정동별 소방 접근성 지수 산출

입력: data/raw/fire_seoul/fire_seoul_2021~2023.csv
출력: data/processed/fire_dispatch_dong.csv

파생 피처:
  cntr_dist_avg   : 행정동별 119안전센터~현장 평균 직선거리 (km)
  dispatch_delay_avg_min : 행정동별 발화~출동요청 평균 지연 (분)
  fire_count_raw  : 공간조인 기반 화재 건수 (검증용)
"""
import pandas as pd
import geopandas as gpd
import numpy as np
from pathlib import Path

RAW_DIR  = Path("data/raw/fire_seoul")
GEO_PATH = Path("data/raw/shp/hangjeongdong_seoul.geojson")
OUT_PATH = Path("data/processed/fire_dispatch_dong.csv")

YEARS = [2021, 2022, 2023]


def hhmmss_to_min(series: pd.Series) -> pd.Series:
    """HHMMSS 정수 (예: 629 = 00:06:29) → 분 단위 float"""
    v = series.fillna(0).astype(int)
    h = v // 10000
    m = (v % 10000) // 100
    s = v % 100
    return h * 60 + m + s / 60


def load_fire(years):
    frames = []
    for yr in years:
        p = RAW_DIR / f"fire_seoul_{yr}.csv"
        if not p.exists():
            print(f"  [경고] 파일 없음: {p}")
            continue
        df = pd.read_csv(p, encoding="utf-8", low_memory=False)
        df["year"] = yr
        frames.append(df)
        print(f"  {yr}: {len(df):,}건")
    return pd.concat(frames, ignore_index=True)


def main():
    print("=== 화재 출동 데이터 전처리 ===\n")

    # ── 1. 데이터 로드 ────────────────────────────────────────
    print("1. 로드 중...")
    df = load_fire(YEARS)
    print(f"   합계: {len(df):,}건\n")

    # ── 2. 서울 필터 + 좌표 유효 필터 ────────────────────────
    df = df[df["GRNDS_CTPV_NM"] == "서울특별시"].copy()
    df = df.dropna(subset=["DAMG_RGN_LOT", "DAMG_RGN_LAT"])
    print(f"2. 서울+좌표 유효: {len(df):,}건")

    # 좌표 범위 이상치 제거
    df = df[
        df["DAMG_RGN_LOT"].between(126.7, 127.3) &
        df["DAMG_RGN_LAT"].between(37.4, 37.72)
    ]
    print(f"   좌표 범위 필터 후: {len(df):,}건\n")

    # ── 3. 파생 컬럼 ─────────────────────────────────────────
    df["dispatch_delay_min"] = hhmmss_to_min(df["DSPT_REQ_TM"])
    # 이상치 제거: 0분 이하 or 60분 초과 → 결측 처리
    df.loc[~df["dispatch_delay_min"].between(0.1, 60), "dispatch_delay_min"] = np.nan

    # CNTR_GRNDS_DSTNC 이상치 (0 또는 100km+) 제거
    df["cntr_dist"] = df["CNTR_GRNDS_DSTNC"].copy()
    df.loc[~df["cntr_dist"].between(0.01, 50), "cntr_dist"] = np.nan

    print(f"3. dispatch_delay_min 유효: {df['dispatch_delay_min'].notna().sum():,}건")
    print(f"   cntr_dist 유효: {df['cntr_dist'].notna().sum():,}건")
    print(f"   dispatch_delay_min 분포: {df['dispatch_delay_min'].describe().round(2).to_dict()}\n")

    # ── 4. Spatial join → 행정동 코드 ───────────────────────
    print("4. Spatial join 중...")
    gdf_fire = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["DAMG_RGN_LOT"], df["DAMG_RGN_LAT"]),
        crs="EPSG:4326"
    )

    gdf_dong = gpd.read_file(GEO_PATH)[["adm_cd", "adm_nm", "geometry"]]
    gdf_dong["adm_cd"] = gdf_dong["adm_cd"].astype(str).str.zfill(10)
    gdf_dong = gdf_dong.set_crs("EPSG:4326", allow_override=True)

    joined = gpd.sjoin(gdf_fire, gdf_dong, how="left", predicate="within")
    matched = joined["adm_cd"].notna().sum()
    print(f"   행정동 매핑 성공: {matched:,} / {len(joined):,} ({matched/len(joined)*100:.1f}%)\n")

    # ── 5. 행정동 단위 집계 ──────────────────────────────────
    print("5. 행정동 집계 중...")
    agg = (
        joined.groupby("adm_cd")
        .agg(
            cntr_dist_avg        =("cntr_dist",         "mean"),
            cntr_dist_median     =("cntr_dist",         "median"),
            dispatch_delay_avg   =("dispatch_delay_min","mean"),
            dispatch_delay_median=("dispatch_delay_min","median"),
            fire_count_raw       =("WRINV_NO",           "count"),
            death_cnt            =("DTH_CNT",            "sum"),
            injury_cnt           =("INJPSN_CNT",         "sum"),
        )
        .reset_index()
    )

    # 행정동명 붙이기
    dong_meta = gdf_dong[["adm_cd", "adm_nm"]].drop_duplicates()
    agg = agg.merge(dong_meta, on="adm_cd", how="left")

    print(f"   집계된 행정동 수: {len(agg)}")
    print(f"\n cntr_dist_avg 분포:\n{agg['cntr_dist_avg'].describe().round(3).to_string()}")
    print(f"\n dispatch_delay_avg 분포:\n{agg['dispatch_delay_avg'].describe().round(2).to_string()}")

    # ── 6. 저장 ──────────────────────────────────────────────
    col_order = [
        "adm_cd", "adm_nm",
        "cntr_dist_avg", "cntr_dist_median",
        "dispatch_delay_avg", "dispatch_delay_median",
        "fire_count_raw", "death_cnt", "injury_cnt",
    ]
    out = agg[col_order].sort_values("cntr_dist_avg", ascending=False)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_PATH}  ({len(out)}개 행정동)")

    # ── 7. 상위/하위 확인 ────────────────────────────────────
    print("\n[소방 접근 거리 상위 10 - 취약]")
    print(out.nlargest(10, "cntr_dist_avg")[["adm_nm", "cntr_dist_avg", "dispatch_delay_avg"]].to_string(index=False))
    print("\n[소방 접근 거리 하위 10 - 양호]")
    print(out.nsmallest(10, "cntr_dist_avg")[["adm_nm", "cntr_dist_avg", "dispatch_delay_avg"]].to_string(index=False))


if __name__ == "__main__":
    main()
