"""MILP solver utilities using OR-Tools CP-SAT.

This module provides a function to solve the binary subset-selection problem:
  choose x_j in {0,1} to minimize |sum_j x_j * value_j - target|
with a small secondary objective to prefer fewer selected codes.

Notes:
- Values are scaled to integers (cents) to keep model integer.
- Uses CP-SAT with a time limit; objective linearizes the absolute difference.
"""
from ortools.sat.python import cp_model
from time import time
from typing import Dict, List, Tuple


def solve_subset_selection(values: Dict[str, float], target: float, *,
                           scale: int = 100,
                           time_limit_seconds: float = 5.0,
                           max_candidates: int = 50,
                           prefer_fewer: bool = True) -> Dict:
    """Solve binary selection of pay codes to approximate target.

    Args:
        values: mapping paycode -> dollar value (float, >= 0).
        target: target dollar amount to approximate (float, >= 0).
        scale: multiplier to convert dollars -> integer units (default cents=100).
        time_limit_seconds: solver time limit.
        max_candidates: if more codes provided, only the largest `max_candidates` are used.
        prefer_fewer: add small penalty to prefer fewer codes when tie.

    Returns a dict:
        {
          'status': 'OPTIMAL'|'FEASIBLE'|'INFEASIBLE'|'UNKNOWN',
          'selected': [list of paycodes],
          'selected_sum': float,  # sum of selected values
          'target': float,
          'abs_error': float,  # absolute error in dollars
          'scaled_error': int,
          'solve_time': float (seconds)
        }
    """
    # Filter and sort candidates by absolute value descending
    items = [(k, float(v)) for k, v in values.items() if float(v) != 0.0]
    if not items:
        return {'status': 'INFEASIBLE', 'selected': [], 'selected_sum': 0.0, 'target': target, 'abs_error': target, 'scaled_error': int(round(target * scale)), 'solve_time': 0.0}

    items.sort(key=lambda kv: abs(kv[1]), reverse=True)
    if len(items) > max_candidates:
        items = items[:max_candidates]

    names = [k for k, _ in items]
    vals = [v for _, v in items]

    scaled_vals = [int(round(v * scale)) for v in vals]
    scaled_target = int(round(target * scale))

    model = cp_model.CpModel()

    x_vars = [model.NewBoolVar(f'x_{i}') for i in range(len(names))]

    # sum_x = sum(x_i * scaled_vals_i)
    sum_var = model.NewIntVar(0, sum(scaled_vals), 'sum_selected')
    model.Add(sum_var == sum(x_vars[i] * scaled_vals[i] for i in range(len(names))))

    # absolute difference linearization: diff >= sum - target ; diff >= target - sum
    max_diff = max(scaled_target, sum(scaled_vals))
    diff = model.NewIntVar(0, max_diff, 'diff')
    model.Add(sum_var - scaled_target <= diff)
    model.Add(scaled_target - sum_var <= diff)

    # Objective: minimize diff primarily, optionally prefer fewer codes
    # Use a large multiplier to prioritize diff over number of codes
    LARGE = max(10**6, scaled_target + 1)
    if prefer_fewer:
        # minimize LARGE * diff + sum(x)
        obj_terms = []
        obj_terms.append(diff * LARGE)
        obj_terms.extend(x_vars)
        model.Minimize(sum(obj_terms))
    else:
        model.Minimize(diff)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = 8

    start = time()
    status = solver.Solve(model)
    elapsed = time() - start

    status_map = {
        cp_model.OPTIMAL: 'OPTIMAL',
        cp_model.FEASIBLE: 'FEASIBLE',
        cp_model.INFEASIBLE: 'INFEASIBLE',
        cp_model.UNKNOWN: 'UNKNOWN',
        cp_model.MODEL_INVALID: 'MODEL_INVALID',
    }

    st = status_map.get(status, 'UNKNOWN')

    selected = []
    for i, name in enumerate(names):
        if solver.Value(x_vars[i]) == 1:
            selected.append(name)

    selected_sum_scaled = sum(solver.Value(x_vars[i]) * scaled_vals[i] for i in range(len(names)))
    abs_error = abs(selected_sum_scaled - scaled_target) / float(scale)

    return {
        'status': st,
        'selected': selected,
        'selected_sum': selected_sum_scaled / float(scale),
        'target': target,
        'abs_error': abs_error,
        'scaled_error': abs(selected_sum_scaled - scaled_target),
        'solve_time': elapsed,
        'num_candidates': len(names),
    }
