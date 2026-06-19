"""
화재 안전 취약지역 위험도 지수 산출

ML 모델 R²≈0 확인 후 데이터 기반 복합 지수로 대체.

설계 원칙:
  1. 퍼센타일 정규화: 극단값 영향 차단, 분포 무관하게 0-100 스케일 통일
  2. 가중 합산: 근거 있는 가중치 (과거이력 > 취약계층 > 건물특성 > 피해심각도)
  3. 2차원 분류: "과거 화재 이력" × "구조적 취약성" → 4분면 대응 전략
  4. 모든 계산 과정 저장 → 시각화·발표 근거 추적 가능

가중치 근거:
  fire_rate_per_10k  (35%): 실제 화재 이력이 미래 위험 가장 강력하게 반영
  ratio_65plus       (25%): 고령자 = 대피 취약, 홀로 사망 비율 높음
  cntr_dist_avg      (20%): 119센터~현장 거리 = 소방 대응 공백 지역
  old_bldg_ratio     (12%): 노후 건물 = 내화 성능 낮음, 전기 배선 위험
  damage_per_fire    (08%): 화재당 피해 규모 = 구조적 심각도
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

OUT_DIR = "data/processed"
os.makedirs(OUT_DIR, exist_ok=True)

# ── 가중치 ──────────────────────────────────────────────────
WEIGHTS = {
    "fire_rate_per_10k": 0.35,
    "ratio_65plus":       0.25,
    "cntr_dist_avg":      0.20,
    "old_bldg_ratio":     0.12,
    "damage_per_fire":    0.08,
}

# ── 2차원 분류 임계값 ────────────────────────────────────────
HIST_THRESH   = 60   # 과거 화재율 상위 40% = "이력 고위험"
STRUCT_THRESH = 60   # 구조 취약 지수 상위 40% = "구조 취약"


def pct_rank(series: pd.Series) -> pd.Series:
    """퍼센타일 순위 0-100 (높을수록 위험)"""
    return series.rank(pct=True) * 100


def load_data():
    df = pd.read_csv(f"{OUT_DIR}/master_table.csv", dtype={"adm_cd": str})
    for col in ["avg_living_pop", "avg_65plus_pop", "ratio_65plus",
                "fire_rate_per_10k", "cntr_dist_avg", "dispatch_delay_avg"]:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    df["gu_cd"] = df["adm_cd"].str[:5]
    df["damage_per_fire"] = np.log1p(df["fire_damage"] / (df["fire_count"] + 1))
    return df


def build_index(df: pd.DataFrame) -> pd.DataFrame:
    # ── 1단계: 퍼센타일 ─────────────────────────────────────
    for col in WEIGHTS:
        df[f"pct_{col}"] = pct_rank(df[col])

    # ── 2단계: 가중 합산 → 종합 위험 지수 (0-100) ───────────
    df["risk_index"] = sum(
        df[f"pct_{col}"] * w for col, w in WEIGHTS.items()
    )
    # 재정규화 0-100
    df["risk_index"] = (
        (df["risk_index"] - df["risk_index"].min()) /
        (df["risk_index"].max() - df["risk_index"].min()) * 100
    ).round(2)

    # ── 3단계: 2차원 분류 ────────────────────────────────────
    # 이력 지수: 화재율 퍼센타일
    df["hist_score"] = df["pct_fire_rate_per_10k"]

    # 구조 취약 지수: 65세비율 + 119거리 + 노후건물 + 피해심각도 (화재율 제외)
    STRUCT_W = {"ratio_65plus": 0.35, "cntr_dist_avg": 0.35, "old_bldg_ratio": 0.20, "damage_per_fire": 0.10}
    struct_raw = sum(df[f"pct_{col}"] * w for col, w in STRUCT_W.items())
    df["struct_score"] = (
        (struct_raw - struct_raw.min()) /
        (struct_raw.max() - struct_raw.min()) * 100
    ).round(2)

    # 4분면 분류
    hi_hist   = df["hist_score"]   >= HIST_THRESH
    hi_struct = df["struct_score"] >= STRUCT_THRESH

    conditions = [
        hi_hist &  hi_struct,
        ~hi_hist & hi_struct,
        hi_hist & ~hi_struct,
    ]
    choices = ["최우선 대응", "잠재 위험", "이력 관리"]
    df["risk_class"] = np.select(conditions, choices, default="관찰 지역")

    # ── 4단계: 5등급 분류 ────────────────────────────────────
    df["risk_grade"] = pd.cut(
        df["risk_index"],
        bins=[-0.1, 20, 40, 60, 80, 100.1],
        labels=["매우낮음", "낮음", "보통", "높음", "매우높음"],
    )

    return df


# ── 시각화 ──────────────────────────────────────────────────

def plot_index_dist(df):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    axes[0].hist(df["risk_index"], bins=25, color="#e74c3c",
                 edgecolor="black", alpha=0.8)
    axes[0].set_title("위험도 지수 분포 (0-100)", fontsize=13)
    axes[0].set_xlabel("종합 위험도 지수")
    axes[0].set_ylabel("행정동 수")
    axes[0].axvline(df["risk_index"].mean(), color="navy",
                    linestyle="--", label=f"평균={df['risk_index'].mean():.1f}")
    axes[0].legend()

    grade_cnt = df["risk_grade"].value_counts().sort_index()
    colors_g  = ["#2ecc71", "#a8e6cf", "#f39c12", "#e67e22", "#e74c3c"]
    axes[1].bar(grade_cnt.index, grade_cnt.values, color=colors_g,
                edgecolor="black", alpha=0.85)
    axes[1].set_title("위험 등급 분포", fontsize=13)
    axes[1].set_xlabel("등급")
    axes[1].set_ylabel("행정동 수")
    for i, v in enumerate(grade_cnt.values):
        axes[1].text(i, v + 1, str(v), ha="center", fontsize=10)

    plt.tight_layout()
    plt.savefig(f"{OUT_DIR}/risk_index_dist.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("저장: risk_index_dist.png")


def plot_2d_matrix(df):
    fig, ax = plt.subplots(figsize=(10, 8))

    CLASS_COLOR = {
        "최우선 대응": "#e74c3c",
        "잠재 위험":   "#e67e22",
        "이력 관리":   "#3498db",
        "관찰 지역":   "#95a5a6",
    }
    CLASS_LABEL = {
        "최우선 대응": f"최우선 대응 ({(df['risk_class']=='최우선 대응').sum()}개)",
        "잠재 위험":   f"잠재 위험 ({(df['risk_class']=='잠재 위험').sum()}개)",
        "이력 관리":   f"이력 관리 ({(df['risk_class']=='이력 관리').sum()}개)",
        "관찰 지역":   f"관찰 지역 ({(df['risk_class']=='관찰 지역').sum()}개)",
    }

    for cls, grp in df.groupby("risk_class"):
        ax.scatter(
            grp["hist_score"], grp["struct_score"],
            c=CLASS_COLOR[cls], label=CLASS_LABEL[cls],
            alpha=0.65, s=40, edgecolors="white", linewidths=0.4,
        )

    # 분류 경계선
    ax.axvline(HIST_THRESH,   color="black", linewidth=1.2, linestyle="--", alpha=0.6)
    ax.axhline(STRUCT_THRESH, color="black", linewidth=1.2, linestyle="--", alpha=0.6)

    # 사분면 라벨
    for x, y, txt, col in [
        (80, 80, "최우선\n대응",   "#e74c3c"),
        (20, 80, "잠재\n위험",     "#e67e22"),
        (80, 20, "이력\n관리",     "#3498db"),
        (20, 20, "관찰\n지역",     "#95a5a6"),
    ]:
        ax.text(x, y, txt, ha="center", va="center", fontsize=11,
                color=col, fontweight="bold", alpha=0.4)

    # 상위 고위험 라벨
    top_label = df[df["risk_class"] == "최우선 대응"].nlargest(10, "risk_index")
    for _, row in top_label.iterrows():
        name = row["adm_nm"].replace("서울특별시 ", "").split(" ", 1)[-1]
        ax.annotate(
            name,
            (row["hist_score"], row["struct_score"]),
            textcoords="offset points", xytext=(5, 5),
            fontsize=7, color="#c0392b",
        )

    ax.set_xlabel("과거 화재 이력 지수 (화재율 퍼센타일)", fontsize=12)
    ax.set_ylabel("구조적 취약성 지수 (65세+, 노후건물, 피해심각도)", fontsize=12)
    ax.set_title("화재 위험도 2차원 분류 매트릭스\n(서울 426개 행정동)", fontsize=14)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_xlim(-5, 105)
    ax.set_ylim(-5, 105)

    plt.tight_layout()
    plt.savefig(f"{OUT_DIR}/risk_2d_matrix.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("저장: risk_2d_matrix.png")


def plot_top_bars(df):
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))

    top30 = df.nlargest(30, "risk_index")
    norm  = plt.Normalize(df["risk_index"].min(), df["risk_index"].max())
    cmap  = plt.cm.RdYlGn_r

    for ax, data, title in [
        (axes[0], top30, "종합 위험 지수 상위 30 행정동"),
        (axes[1], df[df["risk_class"] == "최우선 대응"].sort_values("risk_index", ascending=False),
         f"최우선 대응 지역 ({(df['risk_class']=='최우선 대응').sum()}개)"),
    ]:
        if data.empty:
            ax.set_visible(False)
            continue
        names  = data["adm_nm"].str.replace("서울특별시 ", "").str.split(" ", n=1).str[-1]
        scores = data["risk_index"]
        colors_b = [cmap(norm(s)) for s in scores]

        bars = ax.barh(names[::-1], scores[::-1], color=colors_b[::-1],
                       edgecolor="gray", linewidth=0.4)
        ax.set_xlabel("종합 위험도 지수 (0-100)", fontsize=11)
        ax.set_title(title, fontsize=13)
        for bar, s in zip(bars, scores[::-1]):
            ax.text(s + 0.3, bar.get_y() + bar.get_height() / 2,
                    f"{s:.1f}", va="center", fontsize=8)

    plt.tight_layout()
    plt.savefig(f"{OUT_DIR}/risk_top_bars.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("저장: risk_top_bars.png")


def plot_component_breakdown(df):
    """상위 20 행정동 구성요인 스택 바"""
    top20 = df.nlargest(20, "risk_index").copy()
    names = top20["adm_nm"].str.replace("서울특별시 ", "").str.split(" ", n=1).str[-1]

    comp_cols   = [f"pct_{c}" for c in WEIGHTS]
    comp_labels = ["화재율 (35%)", "65세+비율 (25%)", "119거리 (20%)", "노후건물 (12%)", "화재당피해 (8%)"]
    comp_colors = ["#e74c3c", "#e67e22", "#9b59b6", "#f1c40f", "#3498db"]

    # 가중 기여도
    contrib = pd.DataFrame({
        lbl: top20[col].values * w
        for col, w, lbl in zip(comp_cols, WEIGHTS.values(), comp_labels)
    }, index=names.values)

    fig, ax = plt.subplots(figsize=(12, 8))
    bottom = np.zeros(len(contrib))
    for col, color in zip(comp_labels, comp_colors):
        ax.barh(contrib.index[::-1], contrib[col].values[::-1],
                left=bottom[::-1], color=color, label=col,
                edgecolor="white", linewidth=0.3)
        bottom += contrib[col].values

    ax.set_xlabel("가중 위험도 기여 (퍼센타일 × 가중치)", fontsize=11)
    ax.set_title("상위 20 행정동 위험도 구성요인 분석", fontsize=13)
    ax.legend(loc="lower right", fontsize=9)
    plt.tight_layout()
    plt.savefig(f"{OUT_DIR}/risk_component_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("저장: risk_component_breakdown.png")


def main():
    print("=== 데이터 기반 위험도 지수 산출 ===\n")
    df = load_data()
    df = build_index(df)

    print("위험 등급 분포:")
    print(df["risk_grade"].value_counts().sort_index().to_string())
    print()
    print("2차원 분류 결과:")
    print(df["risk_class"].value_counts().to_string())
    print()

    # 상위 행정동
    print("종합 위험 상위 20:")
    top20 = df.nlargest(20, "risk_index")[
        ["adm_nm", "risk_index", "risk_class", "risk_grade",
         "pct_fire_rate_per_10k", "pct_ratio_65plus", "pct_old_bldg_ratio"]
    ]
    top20.columns = ["행정동", "지수", "분류", "등급", "화재율pct", "65세pct", "노후건물pct"]
    print(top20.to_string(index=False))
    print()

    print("최우선 대응 지역:")
    urgent = df[df["risk_class"] == "최우선 대응"].sort_values("risk_index", ascending=False)
    print(urgent[["adm_nm", "risk_index", "fire_rate_per_10k",
                  "ratio_65plus", "old_bldg_ratio"]].to_string(index=False))

    # 시각화
    print("\n시각화 생성 중...")
    plot_index_dist(df)
    plot_2d_matrix(df)
    plot_top_bars(df)
    plot_component_breakdown(df)

    # 저장
    save_cols = [
        "adm_cd", "adm_nm", "gu_cd",
        "risk_index", "risk_grade", "risk_class",
        "hist_score", "struct_score",
        "pct_fire_rate_per_10k", "pct_ratio_65plus",
        "pct_cntr_dist_avg", "pct_old_bldg_ratio", "pct_damage_per_fire",
        "fire_rate_per_10k", "ratio_65plus", "cntr_dist_avg",
        "old_bldg_ratio", "damage_per_fire", "avg_living_pop", "fire_count",
    ]
    out = df[save_cols].sort_values("risk_index", ascending=False)
    out.to_csv(f"{OUT_DIR}/risk_index_final.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_DIR}/risk_index_final.csv  ({len(out)}개 행정동)")


if __name__ == "__main__":
    main()
