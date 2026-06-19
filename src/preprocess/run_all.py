"""
전처리 파이프라인 순서대로 실행
실행 위치: C:/Users/whddh/firefighter/ (프로젝트 루트)
"""
import subprocess
import sys
import os

scripts = [
    "src/preprocess/01_download_shp.py",
    "src/preprocess/02_fire_seoul.py",
    "src/preprocess/03_population.py",
    "src/preprocess/04_living_population.py",
    "src/preprocess/05_multi_use.py",
    "src/preprocess/06_merge.py",
]

os.chdir("C:/Users/whddh/firefighter")

for script in scripts:
    print(f"\n{'='*50}")
    print(f"실행: {script}")
    print('='*50)
    result = subprocess.run([sys.executable, script], capture_output=False)
    if result.returncode != 0:
        print(f"[오류] {script} 실패 (returncode={result.returncode})")
        print("계속 진행하려면 Enter, 중단하려면 Ctrl+C")
        input()
