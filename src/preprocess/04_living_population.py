"""
행안부 생활인구 전처리
- 2021~2023 zip → 행정동별 평균 생활인구 + 65세이상 비율
- 서울 행정동만 (코드 앞 2자리 11)

컬럼 구조 (UTF-8):
  0: 기준ID, 1: 시간대구분, 2: 행정동코드, 3: 총생활인구수
  4-17: 남성 연령대별 (0-9, 10-14, 15-19, 20-24, 25-29, 30-34,
                       35-39, 40-44, 45-49, 50-54, 55-59, 60-64, 65-69, 70+)
  18-31: 여성 연령대별 (동일 순서)
  → 65세이상 = col[16]+col[17]+col[30]+col[31]
"""
import pandas as pd
import zipfile
import io
import os
import glob

RAW = "data/raw/living_population"
OUT = "data/processed/living_population_dong.csv"

os.makedirs("data/processed", exist_ok=True)

# 컬럼 이름 (위치 기반)
COL_NAMES = [
    "base_date", "time_slot", "adm_cd", "total_pop",
    "m_0_9", "m_10_14", "m_15_19", "m_20_24", "m_25_29",
    "m_30_34", "m_35_39", "m_40_44", "m_45_49", "m_50_54",
    "m_55_59", "m_60_64", "m_65_69", "m_70_plus",
    "f_0_9", "f_10_14", "f_15_19", "f_20_24", "f_25_29",
    "f_30_34", "f_35_39", "f_40_44", "f_45_49", "f_50_54",
    "f_55_59", "f_60_64", "f_65_69", "f_70_plus",
]

def load_one_zip(path):
    with zipfile.ZipFile(path) as z:
        fname = [n for n in z.namelist() if n.endswith(".csv")][0]
        with z.open(fname) as f:
            raw = f.read()
            # 데이터 행이 헤더보다 1열 많음 (trailing comma) → names로 33열 강제 지정
            names33 = COL_NAMES + ["_extra"]
            df = pd.read_csv(
                io.BytesIO(raw), encoding="utf-8",
                header=0, names=names33, skiprows=1,
                engine="python",
            )
    # 행정동코드: 8자리 정수 → 10자리 문자열 ('00' 추가)
    df["adm_cd"] = df["adm_cd"].apply(
        lambda x: str(int(float(x))).zfill(8) + "00" if pd.notna(x) else ""
    )
    return df

def main():
    zip_files = sorted(glob.glob(os.path.join(RAW, "*.zip")))
    print(f"zip 파일 수: {len(zip_files)}")

    all_dfs = []
    for zp in zip_files:
        label = os.path.basename(zp).replace("LOCAL_PEOPLE_DONG_", "").replace(".zip", "")
        print(f"  처리중: {label}", end="")
        try:
            df = load_one_zip(zp)

            # 서울 필터 (앞 2자리 11)
            df = df[df["adm_cd"].str.startswith("11")].copy()

            # 숫자 컬럼 변환
            num_cols = ["total_pop", "m_65_69", "m_70_plus", "f_65_69", "f_70_plus"]
            for c in num_cols:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            # 65세이상 생활인구
            df["pop_65plus"] = (
                df.get("m_65_69", 0).fillna(0)
                + df.get("m_70_plus", 0).fillna(0)
                + df.get("f_65_69", 0).fillna(0)
                + df.get("f_70_plus", 0).fillna(0)
            )

            # 행정동×날짜별 일평균 (시간대 24개 평균)
            daily = (
                df.groupby(["base_date", "adm_cd"])
                .agg(total_pop=("total_pop", "mean"),
                     pop_65plus=("pop_65plus", "mean"))
                .reset_index()
            )
            all_dfs.append(daily)
            print(f" → {df['adm_cd'].nunique()}개 행정동")

        except Exception as e:
            print(f" 오류: {e}")

    if not all_dfs:
        print("처리된 데이터 없음")
        return

    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"\n전체 레코드: {len(combined):,}")

    # 행정동별 전체 기간 평균
    result = (
        combined.groupby("adm_cd")
        .agg(avg_living_pop=("total_pop", "mean"),
             avg_65plus_pop=("pop_65plus", "mean"))
        .reset_index()
    )
    result["ratio_65plus"] = (result["avg_65plus_pop"] / result["avg_living_pop"]).round(4)

    print(f"서울 행정동 수: {len(result)}")
    print(result.head())

    result.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}")

if __name__ == "__main__":
    main()
