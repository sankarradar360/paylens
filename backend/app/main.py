from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os
from fastapi import UploadFile, File, HTTPException
import pandas as pd
import tempfile
import shutil
import traceback
from fastapi import UploadFile, File, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from typing import Dict, Any, Optional
from .solver import solve_subset_selection
from fastapi.responses import FileResponse
from collections import Counter
import uuid
import json
from datetime import datetime
from pathlib import Path

app = FastAPI()

# Directory to persist result files and metadata
RESULTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'results'))
os.makedirs(RESULTS_DIR, exist_ok=True)


@app.get('/health')
async def health():
    return JSONResponse({'status': 'ok'})


@app.get('/api/hello')
async def hello():
    return JSONResponse({'message': 'Hello from PayLens backend!'})


# Serve built frontend when available
DIST_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist'))
if os.path.isdir(DIST_PATH):
    app.mount('/', StaticFiles(directory=DIST_PATH, html=True), name='frontend')
else:
    @app.get('/')
    async def index():
        return {'status': 'frontend not built'}


@app.post('/upload')
async def upload_file(file: UploadFile = File(...)):
    """Accept CSV and Excel files, return a small preview and column list.

    Returns JSON: { filename, rows, columns, preview }
    """
    filename = (file.filename or '').lower()
    if not filename.endswith(('.csv', '.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail='Unsupported file type; only CSV/XLS/XLSX accepted')

    # Save upload to a temporary file then let pandas parse it
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmpf:
            tmp = tmpf.name
            shutil.copyfileobj(file.file, tmpf)

        # parse with pandas
        if filename.endswith('.csv'):
            df = pd.read_csv(tmp)
        else:
            df = pd.read_excel(tmp, engine='openpyxl')

        preview = df.head(5).fillna('').to_dict(orient='records')
        columns = list(df.columns)
        rows = int(len(df))
        return JSONResponse({'filename': file.filename, 'rows': rows, 'columns': columns, 'preview': preview})
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f'Failed to parse uploaded file: {e}')
    finally:
        try:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


@app.get('/results')
async def list_results():
    """List persisted result files and metadata."""
    metas = []
    for p in Path(RESULTS_DIR).glob('*.json'):
        try:
            with open(p, 'r') as fh:
                m = json.load(fh)
                metas.append(m)
        except Exception:
            continue
    # sort by created_at desc
    metas.sort(key=lambda m: m.get('created_at', ''), reverse=True)
    return JSONResponse({'results': metas})


@app.get('/results/{result_id}')
async def get_result(result_id: str):
    """Download a persisted result file by its id."""
    # find matching metadata
    meta_path = os.path.join(RESULTS_DIR, f"{result_id}.json")
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail='result not found')
    with open(meta_path, 'r') as fh:
        meta = json.load(fh)
    stored = os.path.join(RESULTS_DIR, meta.get('stored_name'))
    if not os.path.exists(stored):
        raise HTTPException(status_code=404, detail='file not found')
    return FileResponse(stored, filename=meta.get('filename'))


class InferRequest(BaseModel):
    values: Dict[str, float]
    contribution_amount: float
    contribution_rate: float
    time_limit_seconds: Optional[float] = 5.0
    max_candidates: Optional[int] = 50
    tolerance_pct: Optional[float] = 0.03


@app.post('/infer_row')
async def infer_row(req: InferRequest):
    """Infer eligible pay-code subset for a single employee row using MILP.

    Request JSON: {
      values: { 'REG': 1000.0, 'OT': 50.0, ... },
      contribution_amount: 30.0,
      contribution_rate: 0.03,
      time_limit_seconds: 5.0,
      max_candidates: 20,
      tolerance_pct: 0.03
    }

    Returns solver result and a boolean `within_tolerance` indicating whether
    selected_sum * rate approximates contribution_amount within tolerance.
    """
    # Validate
    if req.contribution_rate == 0:
        raise HTTPException(status_code=400, detail='contribution_rate must be non-zero')

    # Estimate eligible compensation
    eligible_est = req.contribution_amount / req.contribution_rate

    # Filter zero/negative values and run solver
    values = {k: float(v) for k, v in req.values.items()}

    # run solver
    sol = solve_subset_selection(values, eligible_est, scale=100, time_limit_seconds=req.time_limit_seconds, max_candidates=req.max_candidates)

    within_tol = False
    try:
        if sol['status'] in ('OPTIMAL', 'FEASIBLE'):
            selected_sum = sol['selected_sum']
            predicted_contrib = selected_sum * req.contribution_rate
            err = abs(predicted_contrib - req.contribution_amount)
            within_tol = (err <= max(req.tolerance_pct * req.contribution_amount, 1.0))
    except Exception:
        predicted_contrib = None

    return JSONResponse({
        'solver': sol,
        'eligible_est': eligible_est,
        'predicted_contribution': predicted_contrib if 'predicted_contrib' in locals() else None,
        'within_tolerance': within_tol,
    })

@app.post('/infer_file')
async def infer_file(file: UploadFile = File(...),
                     format: str = Query('xlsx', enum=['xlsx', 'csv']),
                     time_limit_seconds: float = Query(5.0),
                     max_candidates: int = Query(50),
                     tolerance_pct: float = Query(0.03),
                     summary_threshold: float = Query(0.5),
                     background_tasks: BackgroundTasks = None):
    """Accept an uploaded CSV/XLSX of payroll rows, run batch inference and
    return a downloadable CSV or Excel with per-employee results and a summary.

    Query params:
      - `format`: 'xlsx' (default) or 'csv'
      - `time_limit_seconds`, `max_candidates`, `tolerance_pct`
      - `summary_threshold`: fraction for suggesting eligible paycodes (default 0.5)
    """
    filename = (file.filename or '').lower()
    if not filename.endswith(('.csv', '.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail='Unsupported file type; only CSV/XLS/XLSX accepted')

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmpf:
            tmp = tmpf.name
            shutil.copyfileobj(file.file, tmpf)

        if filename.endswith('.csv'):
            df = pd.read_csv(tmp)
        else:
            df = pd.read_excel(tmp, engine='openpyxl')

        # Identify paycode columns (exclude known metadata fields)
        meta_cols = {'employee_id', 'contribution_amount', 'contribution_rate', 'period'}
        paycode_cols = [c for c in df.columns if c not in meta_cols]

        results = []
        counter = Counter()

        for _, row in df.iterrows():
            try:
                values = {c: float(row.get(c, 0.0) or 0.0) for c in paycode_cols}
            except Exception:
                values = {c: 0.0 for c in paycode_cols}

            contrib_amt = float(row.get('contribution_amount') or 0.0)
            contrib_rate = float(row.get('contribution_rate') or 0.0)

            if contrib_rate == 0 or contrib_amt == 0:
                eligible_est = None
                sol = {'status': 'SKIP', 'selected': [], 'selected_sum': 0.0}
                predicted_contrib = None
                within_tol = False
            else:
                eligible_est = contrib_amt / contrib_rate
                sol = solve_subset_selection(values, eligible_est, time_limit_seconds=time_limit_seconds, max_candidates=max_candidates)
                for c in sol.get('selected', []):
                    counter[c] += 1
                selected_sum = sol.get('selected_sum', 0.0)
                predicted_contrib = selected_sum * contrib_rate
                err = abs(predicted_contrib - contrib_amt)
                within_tol = (err <= max(tolerance_pct * contrib_amt, 1.0))

            results.append({
                'employee_id': row.get('employee_id', ''),
                'eligible_est': eligible_est,
                'selected': ';'.join(sol.get('selected', [])),
                'selected_sum': sol.get('selected_sum', 0.0),
                'abs_error': sol.get('abs_error', None),
                'solver_status': sol.get('status'),
                'predicted_contribution': predicted_contrib,
                'within_tolerance': within_tol,
            })

        # Build DataFrame for results
        res_df = pd.DataFrame(results)

        # Build summary
        total_rows = len(df)
        summary_rows = [{'paycode': code, 'count': cnt, 'fraction': cnt / total_rows} for code, cnt in counter.items()]
        summary_df = pd.DataFrame(summary_rows).sort_values('count', ascending=False)
        suggested = [code for code, cnt in counter.items() if (cnt / total_rows) >= float(summary_threshold)]

        # Write to temp file
        if format == 'csv':
            out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
            out_path = out_tmp.name
            out_tmp.close()
            res_df.to_csv(out_path, index=False)
            media_type = 'text/csv'
            out_name = f'results_{os.path.basename(file.filename)}.csv'
            # persist file to results directory with UUID prefix
            uid = uuid.uuid4().hex
            dest_name = f"{uid}_{os.path.basename(out_path)}"
            dest_path = os.path.join(RESULTS_DIR, dest_name)
            shutil.move(out_path, dest_path)

            # write metadata
            meta = {
                'id': uid,
                'filename': out_name,
                'stored_name': dest_name,
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'rows': int(total_rows),
                'format': 'csv',
                'suggested': suggested,
            }
            with open(os.path.join(RESULTS_DIR, f"{uid}.json"), 'w') as mf:
                json.dump(meta, mf)

            return FileResponse(dest_path, media_type=media_type, filename=out_name)
        else:
            out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            out_path = out_tmp.name
            out_tmp.close()
            with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
                # include the original uploaded input as its own sheet
                try:
                    df.to_excel(writer, sheet_name='input', index=False)
                except Exception:
                    # non-fatal: continue if input cannot be written
                    pass
                res_df.to_excel(writer, sheet_name='results', index=False)
                summary_df.to_excel(writer, sheet_name='summary', index=False)
                # also write suggested mapping in a small sheet
                pd.DataFrame({'suggested': suggested}).to_excel(writer, sheet_name='suggested', index=False)

            media_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            out_name = f'results_{os.path.basename(file.filename)}.xlsx'
            # persist file to results directory with UUID prefix
            uid = uuid.uuid4().hex
            dest_name = f"{uid}_{os.path.basename(out_path)}"
            dest_path = os.path.join(RESULTS_DIR, dest_name)
            shutil.move(out_path, dest_path)

            # write metadata
            meta = {
                'id': uid,
                'filename': out_name,
                'stored_name': dest_name,
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'rows': int(total_rows),
                'format': 'xlsx',
                'suggested': suggested,
            }
            with open(os.path.join(RESULTS_DIR, f"{uid}.json"), 'w') as mf:
                json.dump(meta, mf)

            return FileResponse(dest_path, media_type=media_type, filename=out_name)

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'Failed to process file: {e}')
    finally:
        try:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
