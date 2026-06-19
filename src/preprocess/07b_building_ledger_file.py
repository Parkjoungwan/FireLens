"""
건축물대장 파일 기반 전처리
(API 키 승인 전 대체 경로)

다운로드 방법:
  https://www.data.go.kr/data/15077736/fileData.do
  → '건축물대장_표제부' 파일 다운로드 (약 2~3GB, 전국)
  → data/raw/building_ledger/ 에 저장

또는:
  https://open.eais.go.kr/opnsvc/opnSvcInfBundle.do
  국토부 건축데이터민간개방시스템에서 시도별 다운로드 (용량 더 작음)

필요 컬럼:
  sggCd (시군구코드), bjdongCd (법정동코드), useAprDay (사용승인일),
  grndFlrCnt (지상층수), mainPurpsCdNm (주용도)
"""
import pandas as pd
import os
import glob
from datetime import datetime

RAW_DIR = "data/raw/building_ledger"
OUT = "data/processed/building_dong.csv"

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

CUTOFF_YEAR = (datetime.now()).year - 30  # 30년 이상
SEOUL_SGG_PREFIX = "11"  # 서울 시군구코드 앞 2자리

# 예상 컬럼명 (data.go.kr 파일 버전)
COL_MAP = {
    "시군구코드": "sigungu_cd",
    "법정동코드": "bjdong_cd",
    "사용승인일": "use_apr_day",
    "지상층수": "grnd_flr_cnt",
    "주용도코드명": "main_purps_nm",
    # open.eais.go.kr 버전
    "sggCd": "sigungu_cd",
    "bjdongCd": "bjdong_cd",
    "useAprDay": "use_apr_day",
    "grndFlrCnt": "grnd_flr_cnt",
    "mainPurpsCdNm": "main_purps_nm",
}

def find_files():
    exts = ["*.csv", "*.CSV", "*.txt"]
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(RAW_DIR, ext)))
        files.extend(glob.glob(os.path.join(RAW_DIR, "**", ext), recursive=True))
    return list(set(files))

def load_file(path):
    for enc in ["utf-8-sig", "euc-kr", "cp949"]:
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False, nrows=5)
            # 컬럼 정규화
            rename = {k: v for k, v in COL_MAP.items() if k in df.columns}
            if rename:
                df_full = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
                return df_full.rename(columns=rename)
        except Exception:
            continue
    return None

def main():
    files = find_files()
    if not files:
        print(f"파일 없음: {RAW_DIR}")
        print("아래 중 하나에서 다운로드 후 위 경로에 저장:")
        print("  https://www.data.go.kr/data/15077736/fileData.do")
        print("  https://open.eais.go.kr/opnsvc/opnSvcInfBundle.do")
        return

    print(f"파일 발견: {len(files)}개")
    all_dfs = []

    for path in files:
        print(f"  로드: {os.path.basename(path)}")
        df = load_file(path)
        if df is None:
            print(f"  인코딩 실패: {path}")
            continue

        needed = ["sigungu_cd", "use_apr_day"]
        if not all(c in df.columns for c in needed):
            print(f"  필수 컬럼 없음. 실제 컬럼: {list(df.columns[:8])}")
            continue

        # 서울만
        df = df[df["sigungu_cd"].astype(str).str.startswith(SEOUL_SGG_PREFIX)].copy()
        print(f"  서울 건물: {len(df):,}건")
        all_dfs.append(df)

    if not all_dfs:
        print("처리 가능한 데이터 없음")
        return

    df = pd.concat(all_dfs, ignore_index=True)
    print(f"\n총 서울 건물: {len(df):,}건")

    # 사용승인연도 추출
    def parse_year(s):
        s = str(s).strip()
        return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None

    df["use_year"] = df["use_apr_day"].apply(parse_year)
    df["is_old"] = (df["use_year"] <= CUTOFF_YEAR).where(df["use_year"].notna(), False).astype(int)

    if "grnd_flr_cnt" in df.columns:
        df["grnd_flr_cnt"] = pd.to_numeric(df["grnd_flr_cnt"], errors="coerce")

    # 시군구+법정동 집계
    grp_cols = ["sigungu_cd"]
    if "bjdong_cd" in df.columns:
        grp_cols.append("bjdong_cd")

    agg_dict = {"total_bldg": ("is_old", "count"), "old_bldg": ("is_old", "sum")}
    if "grnd_flr_cnt" in df.columns:
        agg_dict["avg_floors"] = ("grnd_flr_cnt", "mean")

    agg = df.groupby(grp_cols).agg(**agg_dict).reset_index()
    agg["old_bldg_ratio"] = (agg["old_bldg"] / agg["total_bldg"]).round(4)

    print(f"\n집계 결과: {len(agg)}개 법정동")
    print(f"노후건물 비율 분포:\n{agg['old_bldg_ratio'].describe().round(3)}")

    agg.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}")

if __name__ == "__main__":
    main()
