"""
전체 데이터 통합 테이블 생성
기준: 서울 행정동 (adm_cd 10자리)

컬럼 구성:
- adm_cd: 행정동코드
- adm_nm: 행정동명
- fire_count: 연평균 화재 건수 (2021-2023)
- fire_death: 연평균 사망자
- fire_injury: 연평균 부상자
- fire_damage: 연평균 재산피해액
- pop_total: 총인구수 (2023)
- pop_65plus_ratio: 65세 이상 인구 비율
- pop_1person_ratio: 1인가구 비율 (세대 기준 근사치)
- avg_living_pop: 평균 생활인구 (행안부)
- multi_use_cnt: 다중이용업소 수
- fire_rate: 인구 1만명당 화재 건수 (Y값 후보)
"""
import pandas as pd
import geopandas as gpd
import os

PROCESSED = "data/processed"
OUT = "data/processed/master_table.csv"

def load(filename):
    path = os.path.join(PROCESSED, filename)
    if not os.path.exists(path):
        print(f"  [경고] 파일 없음: {path}")
        return None
    return pd.read_csv(path, encoding="utf-8-sig", dtype={"adm_cd": str})

def main():
    print("=== 통합 테이블 생성 ===")

    # 행정동 기준 목록 (GeoJSON)
    shp = gpd.read_file("data/raw/shp/hangjeongdong_seoul.geojson")
    base = shp[["adm_cd", "adm_nm"]].copy()
    base["adm_cd"] = base["adm_cd"].astype(str).str.zfill(10)
    print(f"기준 행정동: {len(base)}개")

    # 화재 데이터 (연평균, 2021-2023)
    fire = load("fire_seoul_dong.csv")
    if fire is not None:
        fire["adm_cd"] = fire["adm_cd"].astype(str).str.zfill(10)
        fire_avg = (
            fire[fire["year"].isin([2021, 2022, 2023])]
            .groupby("adm_cd")
            .agg(
                fire_count=("fire_count", "mean"),
                fire_death=("death_cnt", "mean"),
                fire_injury=("injury_cnt", "mean"),
                fire_damage=("property_damage", "mean"),
            )
            .reset_index()
        )
        base = base.merge(fire_avg, on="adm_cd", how="left")
        print(f"화재 데이터 병합 완료: {fire_avg['adm_cd'].nunique()}개 행정동")

    # 인구 데이터
    pop = load("population_dong.csv")
    if pop is not None:
        pop["adm_cd"] = pop["adm_cd"].astype(str).str.zfill(10)
        # 2023년 총인구 컬럼 찾기
        total_col = [c for c in pop.columns if "2023" in c and "총인구" in c]
        household_col = [c for c in pop.columns if "2023" in c and "세대" in c]

        if total_col:
            pop["pop_total"] = pd.to_numeric(
                pop[total_col[0]].astype(str).str.replace(",", ""), errors="coerce"
            )
        if household_col:
            pop["pop_household"] = pd.to_numeric(
                pop[household_col[0]].astype(str).str.replace(",", ""), errors="coerce"
            )

        pop_merge = pop[["adm_cd"] + (["pop_total"] if total_col else []) + (["pop_household"] if household_col else [])]
        base = base.merge(pop_merge, on="adm_cd", how="left")
        print(f"인구 데이터 병합 완료")

    # 생활인구 (avg_living_pop + ratio_65plus)
    living = load("living_population_dong.csv")
    if living is not None:
        living["adm_cd"] = living["adm_cd"].astype(str).str.zfill(10)
        base = base.merge(
            living[["adm_cd", "avg_living_pop", "avg_65plus_pop", "ratio_65plus"]],
            on="adm_cd", how="left"
        )
        print(f"생활인구 병합 완료")

    # 다중이용업소
    muf = load("multi_use_dong.csv")
    if muf is not None:
        muf["adm_cd"] = muf["adm_cd"].astype(str).str.zfill(10)
        base = base.merge(muf[["adm_cd", "multi_use_cnt"]], on="adm_cd", how="left")
        base["multi_use_cnt"] = base["multi_use_cnt"].fillna(0)
        print(f"다중이용업소 병합 완료")

    # 건축물대장 (구 단위 노후건물비율)
    bldg = load("building_dong.csv")
    if bldg is not None:
        bldg["sigungu_cd"] = bldg["sigungu_cd"].astype(str).str.zfill(5)
        base["sigungu_cd"] = base["adm_cd"].astype(str).str[:5]
        base = base.merge(
            bldg[["sigungu_cd", "old_bldg_ratio", "avg_floors"]],
            on="sigungu_cd", how="left"
        )
        base = base.drop(columns=["sigungu_cd"])
        print(f"건축물대장 병합 완료 (구 단위 노후건물비율)")

    # 화재 출동 접근성 (행정동 단위 — 09_fire_dispatch.py 결과)
    dispatch = load("fire_dispatch_dong.csv")
    if dispatch is not None:
        dispatch["adm_cd"] = dispatch["adm_cd"].astype(str).str.zfill(10)
        base = base.merge(
            dispatch[["adm_cd", "cntr_dist_avg", "dispatch_delay_avg"]],
            on="adm_cd", how="left"
        )
        print(f"출동 접근성 병합 완료")

    # Y값 파생: 생활인구 1만명당 화재 건수 (pop_total 대신 avg_living_pop 사용)
    if "fire_count" in base.columns and "avg_living_pop" in base.columns:
        base["fire_rate_per_10k"] = (
            base["fire_count"] / base["avg_living_pop"] * 10000
        ).round(4)

    # 주민등록 인구 컬럼 제거 (행정동 단위 데이터 미확보)
    base = base.drop(columns=["pop_total", "pop_household"], errors="ignore")

    print(f"\n최종 통합 테이블: {len(base)}행 × {len(base.columns)}컬럼")
    print(f"컬럼: {list(base.columns)}")
    print(f"결측치 현황:\n{base.isnull().sum()}")

    base.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT}")

if __name__ == "__main__":
    main()
