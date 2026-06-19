import pandas as pd, numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GroupKFold, KFold
from sklearn.metrics import r2_score
import warnings; warnings.filterwarnings('ignore')

df = pd.read_csv('data/processed/master_table.csv', dtype={'adm_cd': str})
for col in ['avg_living_pop','avg_65plus_pop','ratio_65plus','fire_rate_per_10k']:
    df[col] = df[col].fillna(df[col].median())

df['gu_cd'] = df['adm_cd'].str[:5]
df['log_avg_living_pop'] = np.log1p(df['avg_living_pop'])
df['damage_per_fire'] = np.log1p(df['fire_damage'] / (df['fire_count'] + 1))
df['injury_per_fire'] = df['fire_injury'] / (df['fire_count'] + 1)

FEAT_B = ['log_avg_living_pop','ratio_65plus','old_bldg_ratio','avg_floors','damage_per_fire','injury_per_fire']
y     = np.log(df['fire_rate_per_10k'])
y_raw = df['fire_rate_per_10k']
groups = df['gu_cd']
X = df[FEAT_B]

def make_ridge():
    return Pipeline([('sc', StandardScaler()), ('m', Ridge(alpha=1.0))])

# ── GroupKFold 폴드별 R2 ────────────────────────────────────
gkf = GroupKFold(n_splits=5)
oof_gkf = np.zeros(len(X))
print("GroupKFold 폴드별 R2:")
for i, (tr, val) in enumerate(gkf.split(X, y, groups=groups)):
    m = make_ridge()
    m.fit(X.iloc[tr], y.iloc[tr])
    oof_gkf[val] = m.predict(X.iloc[val])
    val_gu = groups.iloc[val].unique().tolist()
    fold_r2 = r2_score(np.exp(y.iloc[val]), np.exp(oof_gkf[val]))
    print(f"  fold {i}: {len(val_gu)}개 구, n={len(val)}, R2={fold_r2:.4f}, gu={val_gu[:3]}...")

gkf_r2_orig = r2_score(np.exp(y), np.exp(oof_gkf))
gkf_r2_log  = r2_score(y, oof_gkf)
print(f"\nGroupKFold 전체 R2 (원값)={gkf_r2_orig:.4f}  (log)={gkf_r2_log:.4f}")

# ── random KFold ─────────────────────────────────────────────
kf = KFold(n_splits=5, shuffle=True, random_state=42)
oof_kf = np.zeros(len(X))
for tr, val in kf.split(X, y):
    m = make_ridge()
    m.fit(X.iloc[tr], y.iloc[tr])
    oof_kf[val] = m.predict(X.iloc[val])
kf_r2_orig = r2_score(np.exp(y), np.exp(oof_kf))
kf_r2_log  = r2_score(y, oof_kf)
print(f"random KFold   R2 (원값)={kf_r2_orig:.4f}  (log)={kf_r2_log:.4f}")

print(f"\n실제 R2 차이 (낙관적 편향): {kf_r2_orig - gkf_r2_orig:.4f}")

# ── 구 간 / 구 내 분산 분해 ──────────────────────────────────
print("\n분산 분해 (log Y):")
gu_mean_y = y.groupby(df['gu_cd']).transform('mean')
ss_tot     = ((y - y.mean())**2).sum()
ss_between = ((gu_mean_y - y.mean())**2).sum()
ss_within  = ((y - gu_mean_y)**2).sum()
print(f"  구 간 분산: {ss_between/ss_tot*100:.1f}%")
print(f"  구 내 분산: {ss_within/ss_tot*100:.1f}%")

# ── 구 내 행정동 차이가 피처와 상관 있는가 ──────────────────
print("\n구 내 demeaned 피처-Y 상관:")
X_dm = X - X.groupby(df['gu_cd']).transform('mean')
y_dm = y - gu_mean_y
for col in FEAT_B:
    r = np.corrcoef(X_dm[col], y_dm)[0,1]
    print(f"  {col:25}: r={r:.3f}")
