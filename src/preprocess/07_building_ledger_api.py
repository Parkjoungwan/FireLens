"""
건축물대장 표제부 수집 (BldRgstHubService, 신규 엔드포인트)

인증: requests.get(params=...) + urllib.parse.unquote(인코딩키)
수집: 서울 467개 법정동 × 전체 페이지
집계: 구 단위 (sigunguCd 5자리) → 행정동에 구 평균값 할당

법정동코드 출처: 행안부 법정동코드전체자료 (FinanceData GitHub gist)
노후 기준: 사용승인일 기준 30년 이상 (useAprDay[:4] <= CUTOFF_YEAR)
"""
import requests
import json
import time
import os
import pandas as pd
import urllib.request
from urllib.parse import unquote
import urllib3
urllib3.disable_warnings()

API_KEY = unquote(open("data/keys/building_ledger_api_key.txt").read().strip())
BASE_URL = "http://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"

CUTOFF_YEAR = 2026 - 30  # 30년 이상

BJDONG_CODE_URL = (
    "https://gist.githubusercontent.com/FinanceData/4b0a6e1818cea9e77496e57b84bb4565"
    "/raw/b682e526c7e9ebd1c30f688b789aa018f396e1c9"
    "/%25EB%25B2%2595%25EC%25A0%2595%25EB%258F%2599%25EC%25BD%2594%25EB%2593%259C%25EC%25A0%2584%25EC%25B2%25B4%25EC%259E%2590%25EB%25A3%258C.txt"
)

SEOUL_SGG = {
    "11110": "종로구", "11140": "중구",    "11170": "용산구",  "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구",  "11290": "성북구",
    "11305": "강북구", "11320": "도봉구",  "11350": "노원구",  "11380": "은평구",
    "11410": "서대문구","11440": "마포구", "11470": "양천구",  "11500": "강서구",
    "11530": "구로구", "11545": "금천구",  "11560": "영등포구","11590": "동작구",
    "11620": "관악구", "11650": "서초구",  "11680": "강남구",  "11710": "송파구",
    "11740": "강동구",
}

OUT_RAW_DIR = "data/raw/building_ledger"
OUT_BJDONG  = "data/raw/building_ledger/seoul_bjdong_codes.json"
CHECKPOINT  = "data/raw/building_ledger/checkpoint.json"
OUT_RAW_CSV = "data/raw/building_ledger/building_raw.csv"
OUT         = "data/processed/building_dong.csv"

os.makedirs(OUT_RAW_DIR, exist_ok=True)
os.makedirs("data/processed", exist_ok=True)


def get_seoul_bjdong_codes():
    """서울 법정동코드 467개 반환 (행안부 법정동코드전체자료)"""
    if os.path.exists(OUT_BJDONG):
        with open(OUT_BJDONG, encoding="utf-8") as f:
            return json.load(f)

    print("법정동코드 다운로드 중...")
    with urllib.request.urlopen(BJDONG_CODE_URL, timeout=30) as r:
        raw = r.read().decode("utf-8")

    codes = []
    for line in raw.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        code, name, status = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if (code.startswith("11") and status == "존재"
                and len(code) == 10 and not code.endswith("00000")):
            sgg = code[:5]
            bjd = code[5:]
            codes.append({"sigunguCd": sgg, "bjdongCd": bjd, "name": name})

    with open(OUT_BJDONG, "w", encoding="utf-8") as f:
        json.dump(codes, f, ensure_ascii=False, indent=2)
    print(f"서울 법정동 {len(codes)}개 저장: {OUT_BJDONG}")
    return codes


def fetch_page(sigungu_cd, bjdong_cd, page_no, rows=1000):
    params = {
        "serviceKey": API_KEY,
        "numOfRows": rows,
        "pageNo": page_no,
        "sigunguCd": sigungu_cd,
        "bjdongCd": bjdong_cd,
        "_type": "json",
    }
    for attempt in range(3):
        try:
            r = requests.get(BASE_URL, params=params, verify=False, timeout=30)
            data = r.json()
            # 응답 구조: {"response": {"header": ..., "body": ...}}
            # 또는:       {"header": ..., "body": ...}
            root = data.get("response", data)
            header = root.get("header", {})
            body = root.get("body", {})
            if header.get("resultCode") not in ("00", None):
                print(f"  API 오류: {header}")
                return [], 0
            total = int(body.get("totalCount", 0))
            items_wrap = body.get("items", {})
            if not items_wrap:
                return [], total
            item = items_wrap.get("item", [])
            if isinstance(item, dict):
                item = [item]
            return item, total
        except Exception as e:
            print(f"  오류 (시도 {attempt+1}/3): {e}")
            time.sleep(2 ** attempt)
    return [], 0


def collect_all():
    codes = get_seoul_bjdong_codes()

    # 체크포인트
    done = set()
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, encoding="utf-8") as f:
            done = set(json.load(f))
        print(f"체크포인트: {len(done)}/{len(codes)} 완료")

    all_records = []
    # 기존 raw 있으면 로드
    if os.path.exists(OUT_RAW_CSV) and done:
        all_records = pd.read_csv(OUT_RAW_CSV, dtype=str).to_dict("records")
        print(f"기존 데이터 {len(all_records)}건 로드")

    for i, entry in enumerate(codes):
        sgg = entry["sigunguCd"]
        bjd = entry["bjdongCd"]
        key = f"{sgg}_{bjd}"

        if key in done:
            continue

        # 1페이지로 totalCount 확인
        items, total = fetch_page(sgg, bjd, 1, rows=1000)
        if total == 0:
            done.add(key)
            continue

        total_pages = (total + 999) // 1000
        dong_records = list(items)

        for pg in range(2, total_pages + 1):
            items2, _ = fetch_page(sgg, bjd, pg, rows=1000)
            dong_records.extend(items2)
            time.sleep(0.05)

        for rec in dong_records:
            all_records.append({
                "sigungu_cd": sgg,
                "bjdong_cd":  bjd,
                "use_apr_day": str(rec.get("useAprDay", "")),
                "grnd_flr_cnt": str(rec.get("grndFlrCnt", "")),
                "main_purps_cd": str(rec.get("mainPurpsCd", "")),
            })

        done.add(key)

        # 진행 상황 저장 (10개마다)
        if len(done) % 10 == 0:
            pd.DataFrame(all_records).to_csv(OUT_RAW_CSV, index=False, encoding="utf-8-sig")
            with open(CHECKPOINT, "w", encoding="utf-8") as f:
                json.dump(list(done), f)
            print(f"  [{len(done)}/{len(codes)}] 누적 {len(all_records):,}건 (최근: {entry['name']})")

        time.sleep(0.1)

    # 최종 저장
    pd.DataFrame(all_records).to_csv(OUT_RAW_CSV, index=False, encoding="utf-8-sig")
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(list(done), f)

    print(f"\n수집 완료: {len(all_records):,}건, 법정동 {len(done)}개")
    return pd.DataFrame(all_records)


def aggregate(df):
    """구 단위 집계 → 노후건물비율, 평균층수"""
    def parse_year(s):
        s = str(s).strip()
        return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None

    df["use_year"] = df["use_apr_day"].apply(parse_year)
    df["is_old"] = df["use_year"].apply(
        lambda y: 1 if y and y <= CUTOFF_YEAR else 0
    )
    df["grnd_flr_cnt"] = pd.to_numeric(df["grnd_flr_cnt"], errors="coerce")

    # 구 단위 집계
    agg = (
        df.groupby("sigungu_cd")
        .agg(
            total_bldg=("is_old", "count"),
            old_bldg=("is_old", "sum"),
            avg_floors=("grnd_flr_cnt", "mean"),
        )
        .reset_index()
    )
    agg["old_bldg_ratio"] = (agg["old_bldg"] / agg["total_bldg"]).round(4)
    agg["avg_floors"] = agg["avg_floors"].round(2)
    agg["sigungu_nm"] = agg["sigungu_cd"].map(SEOUL_SGG)

    print("\n=== 서울 구별 노후건물비율 (사용승인 30년+) ===")
    print(
        agg[["sigungu_nm", "total_bldg", "old_bldg_ratio", "avg_floors"]]
        .sort_values("old_bldg_ratio", ascending=False)
        .to_string(index=False)
    )
    return agg


def main():
    print("=== 건축물대장 표제부 수집 (BldRgstHubService) ===")
    print(f"노후 기준: {CUTOFF_YEAR}년 이전 사용승인")

    # 연결 테스트
    print("\nAPI 연결 테스트...")
    items, total = fetch_page("11110", "10100", 1, rows=3)
    if items:
        print(f"  성공! 종로구 청운동 총 건물: {total}건")
    else:
        print("  응답 없음")
        return

    df = collect_all()

    if df.empty:
        print("수집 데이터 없음")
        return

    agg = aggregate(df)
    agg.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT}")
    print("다음 단계: 06_merge.py 재실행하여 master_table에 구 단위 노후건물비율 통합")


if __name__ == "__main__":
    main()
