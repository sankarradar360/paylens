"""Generate sample_payroll.xlsx from sample_payroll.csv

Run:
    python3 test_data/generate_excel.py

This writes test_data/sample_payroll.xlsx using pandas/openpyxl.
"""
import pandas as pd
from pathlib import Path

csv_path = Path(__file__).parent / 'sample_payroll.csv'
xlsx_path = Path(__file__).parent / 'sample_payroll.xlsx'

df = pd.read_csv(csv_path)
df.to_excel(xlsx_path, index=False)
print('Wrote', xlsx_path)
