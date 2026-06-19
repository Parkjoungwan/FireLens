"""
주민등록 인구통계 전처리
- 행정동 단위 행 필터링 (코드 10자리, 읍면동 레벨)
- 서울 행정동만 추출 (코드 앞 2자리 = 11)
- 2023년 기준: 고령인구비율(65세+), 1인가구비율
"""
import pandas as pd
import re
import os

RAW = "data/raw/population/population_2021_2025.csv"
OUT = "data/processed/population_dong.csv"

os.makedirs("data/processed", exist_ok=True)

def load_population():
    df = pd.read_csv(RAW, encoding="euc-kr", thousands=",")
    return df

def extract_dong_code(region_str):
    """'행정동명 (코드)' 형태에서 코드 추출"""
    m = re.search(r"\((\d{10})\)", str(region_str))
    return m.group(1) if m else None

def is_dong_level(code):
    """읍면동 레벨: 앞 5자리 시군구 채워져 있고, 6~8자리 읍면동 비어있지 않고, 9~10자리(리) 00"""
    if not code or len(code) != 10:
        return False
    # 시군구코드: [2:5], 읍면동코드: [5:8], 리코드: [8:10]
    sgg = code[2:5]
    dong = code[5:8]
    ri = code[8:10]
    return sgg != "000" and dong != "000" and ri == "00"

def main():
    print("주민등록 인구 로드...")
    df = load_population()

    region_col = df.columns[0]
    print(f"  지역 컬럼: {region_col}")
    print(f"  전체 행: {len(df):,}")

    # 코드 추출
    df["adm_cd"] = df[region_col].apply(extract_dong_code)

    # 행정동 레벨 필터
    df = df[df["adm_cd"].apply(is_dong_level)].copy()
    print(f"  행정동 행: {len(df):,}")

    # 서울만 (코드 앞 2자리 11)
    df_seoul = df[df["adm_cd"].str.startswith("11")].copy()
    print(f"  서울 행정동: {len(df_seoul):,}")

    # 2023년 기준 컬럼 선택
    # 컬럼명 패턴: '2023년_총인구수', '2023년_세대수' 등
    cols_2023 = [c for c in df.columns if "2023" in str(c)]
    print(f"  2023년 컬럼: {cols_2023}")

    # 행정동명 추출 (괄호 앞 텍스트)
    df_seoul["adm_nm"] = df_seoul[region_col].apply(
        lambda x: re.sub(r"\s*\(\d+\).*", "", str(x)).strip()
    )

    result = df_seoul[["adm_cd", "adm_nm"] + cols_2023].copy()

    # 컬럼 이름 정리 (한글 그대로 사용)
    result.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}")
    print(result.head())

if __name__ == "__main__":
    main()
