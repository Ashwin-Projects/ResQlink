import os
import time
import csv
import json
from runner import load_csv
from ablations import Ablations
from metrics import MetricsCalculator

def load_csv(path):
    with open(path, 'r') as f:
        return list(csv.DictReader(f))

def test_scalability(size: int, seeds: list = None):
    """Test scalability at given size."""
    filepath = f'../scenario/scale_requests_{size}.csv'
    if not os.path.exists(filepath):
        print(f"File {filepath} not found. Generate via Phase 5 scale generator first.")
        return None

    print(f"\n=== Scalability Test: {size:,} requests ===")
    reqs = load_csv(filepath)
    res = load_csv('../scenario/resources.csv')

    if seeds is None:
        seeds = [42]

    results = []
    for seed in seeds:
        import random
        random.seed(seed)

        start = time.time()
        result = Ablations.run_ablation(reqs, res, 'D_full_resqlink')
        elapsed = time.time() - start

        # Calculate metrics
        calc = MetricsCalculator(result, None, reqs, res)
        summary = calc.get_summary()

        print(f"  Seed {seed}: {elapsed:.2f}s | Rows: {summary['db_work']['total_rows_scanned']} | "
              f"Coverage: {summary['coverage_percent']:.1f}% | p95: {summary['latency_ms']['p95']:.1f}ms")

        results.append({
            'seed': seed,
            'time_seconds': elapsed,
            'metrics': summary
        })

    return {
        'size': size,
        'results': results
    }

def run_all_scalability_tests():
    """Run scalability tests at 10k, 100k, 1M."""
    sizes = [10000, 100000, 1000000]
    seeds = [42, 123, 999]  # Use 3 seeds for scale tests

    all_results = {}

    for size in sizes:
        result = test_scalability(size, seeds)
        if result:
            all_results[size] = result

    # Save results
    os.makedirs('results', exist_ok=True)
    with open('results/scalability.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    print("\n=== Scalability Summary ===")
    for size, data in all_results.items():
        times = [r['time_seconds'] for r in data['results']]
        rows = [r['metrics']['db_work']['total_rows_scanned'] for r in data['results']]
        print(f"  {size:>7,}: {sum(times)/len(times):.2f}s avg | {sum(rows)/len(rows):.0f} rows avg")

    return all_results

def test_scalability_comparison(size: int):
    """Compare full rescan vs incremental at scale."""
    filepath = f'../scenario/scale_requests_{size}.csv'
    if not os.path.exists(filepath):
        return None

    reqs = load_csv(filepath)
    res = load_csv('../scenario/resources.csv')

    print(f"\n=== Scale Comparison: {size:,} requests ===")

    # Full rescan
    start = time.time()
    full_result = Ablations.run_ablation(reqs, res, 'H_full_rescan')
    full_time = time.time() - start
    full_calc = MetricsCalculator(full_result, None, reqs, res)
    full_metrics = full_calc.get_summary()

    # Incremental
    start = time.time()
    inc_result = Ablations.run_ablation(reqs, res, 'D_full_resqlink')
    inc_time = time.time() - start
    inc_calc = MetricsCalculator(inc_result, None, reqs, res)
    inc_metrics = inc_calc.get_summary()

    db_reduction = inc_calc.calculate_db_work_reduction(full_metrics['db_work']['total_rows_scanned'])

    print(f"  Full Rescan:  {full_time:.2f}s | {full_metrics['db_work']['total_rows_scanned']:,} rows | "
          f"p95: {full_metrics['latency_ms']['p95']:.1f}ms")
    print(f"  Incremental:  {inc_time:.2f}s | {inc_metrics['db_work']['total_rows_scanned']:,} rows | "
          f"p95: {inc_metrics['latency_ms']['p95']:.1f}ms")
    print(f"  DB Work Reduction: {db_reduction:.1f}%")

    return {
        'size': size,
        'full_rescan': {'time': full_time, 'metrics': full_metrics},
        'incremental': {'time': inc_time, 'metrics': inc_metrics},
        'db_work_reduction_percent': db_reduction
    }

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            run_all_scalability_tests()
        elif sys.argv[1] == '--compare':
            for size in [10000, 100000]:
                test_scalability_comparison(size)
        else:
            size = int(sys.argv[1])
            test_scalability(size)
    else:
        # Default: test 10k if available
        if os.path.exists('../scenario/scale_requests_10000.csv'):
            test_scalability(10000)
        else:
            print("No scale data found. Run Phase 5 generator first.")