import sys
from pathlib import Path
import pandas as pd

# ensure repo root on path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.app.solver import solve_subset_selection

CSV = Path(__file__).parent / 'sample_payroll.csv'

df = pd.read_csv(CSV)

paycode_cols = [c for c in df.columns if c not in ('employee_id','contribution_amount','contribution_rate','period')]

results = []
from collections import Counter
counter = Counter()

for i, row in df.iterrows():
    values = {c: float(row[c]) for c in paycode_cols}
    contrib_amt = float(row['contribution_amount'])
    contrib_rate = float(row['contribution_rate'])
    if contrib_rate == 0:
        eligible_est = None
        sol = {'status':'SKIP','selected':[]}
    else:
        eligible_est = contrib_amt / contrib_rate
        sol = solve_subset_selection(values, eligible_est, time_limit_seconds=2.0, max_candidates=20)
        for c in sol.get('selected',[]):
            counter[c] += 1
    results.append({'employee_id': row.get('employee_id',''), 'eligible_est': eligible_est, 'solver': sol})

# print per-employee results
print('Per-employee results:')
for r in results:
    print(r['employee_id'], 'eligible_est=', r['eligible_est'], 'selected=', r['solver'].get('selected'))

print('\nSelection counts:')
for code, cnt in counter.most_common():
    print(code, cnt, '/', len(df), f"({cnt/len(df):.2f})")

# Suggest mapping: codes selected in >=50% employees
threshold = 0.5
mapping = [code for code, cnt in counter.items() if cnt / len(df) >= threshold]
print('\nSuggested eligible paycodes (>=50%):', mapping)
