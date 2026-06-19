"""
소방청 다중이용업소 현황 전처리
- 2021~2023 CSV 합치기
- 서울 데이터만 필터 (주소에서 '서울' 포함)
- 주소에서 행정동 추출 → 행정동 GeoJSON으로 코드 매핑
- 행정동별 현재 영업중(USE_YN=Y) 업소 수 집계
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import re
import os

RAW = "data/raw/multi_use_facilities"
SHP = "data/raw/shp/hangjeongdong_seoul.geojson"
OUT = "data/processed/multi_use_dong.csv"

os.makedirs("data/processed", exist_ok=True)

YEARS = [2021, 2022, 2023]

def load_muf():
    dfs = []
    for yr in YEARS:
        path = os.path.join(RAW, f"muf_{yr}.csv")
        df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        df["year"] = yr
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)

def filter_seoul(df):
    addr_col = "CONM_ADDR"
    if addr_col not in df.columns:
        print(f"컬럼 없음: {addr_col}, 컬럼 목록:", list(df.columns))
        return df
    return df[df[addr_col].str.contains("서울", na=False)].copy()

def extract_dong_from_addr(addr):
    """주소에서 동 추출: '서울특별시 XX구 XX동' 패턴"""
    m = re.search(r"(\S+동|\S+가|\S+로\d+가)\b", str(addr))
    return m.group(1) if m else None

def main():
    print("다중이용업소 로드...")
    df = load_muf()
    print(f"  전국: {len(df):,}건")

    df_seoul = filter_seoul(df)
    print(f"  서울: {len(df_seoul):,}건")

    # 영업 중인 업소만
    if "USE_YN" in df_seoul.columns:
        df_seoul = df_seoul[df_seoul["USE_YN"] == "Y"].copy()
        print(f"  영업중: {len(df_seoul):,}건")

    # 주소에서 동 이름 추출
    df_seoul["dong_nm"] = df_seoul["CONM_ADDR"].apply(extract_dong_from_addr)

    # 행정동 GeoJSON으로 동 이름 → adm_cd 매핑
    dong_gdf = gpd.read_file(SHP)
    # adm_nm에서 '동' 이름만 추출해서 매핑 테이블 생성
    dong_map = dong_gdf[["adm_cd", "adm_nm"]].copy()
    dong_map["dong_short"] = dong_map["adm_nm"].str.extract(r"(\S+동|\S+가|\S+로\d+가)$")

    df_seoul = df_seoul.merge(
        dong_map[["adm_cd", "dong_short"]].dropna(),
        left_on="dong_nm",
        right_on="dong_short",
        how="left"
    )

    matched = df_seoul["adm_cd"].notna().sum()
    print(f"  행정동 매핑 성공: {matched:,} / {len(df_seoul):,}")

    # 최근 연도(2023) 기준 행정동별 업소 수
    agg = (
        df_seoul[df_seoul["year"] == 2023]
        .groupby("adm_cd")
        .size()
        .reset_index(name="multi_use_cnt")
    )
    print(f"  행정동 수: {len(agg)}")

    agg.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}")
    print(agg.head())

if __name__ == "__main__":
    main()
