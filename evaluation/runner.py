import csv
import json
import os
import copy
from baselines import Baselines
from ablations import Ablations
from metrics import MetricsCalculator, compare_configs

def load_csv(path):
    with open(path, 'r') as f:
        return list(csv.DictReader(f))

def load_gt(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return None

def run_evaluation(seed: int = 42):
    """Run complete evaluation for a single seed."""
    print(f"\n=== Running Evaluation (Seed: {seed}) ===")

    # Set seed for reproducibility
    import random
    random.seed(seed)

    print("Loading Phase 5 Scenario Data...")
    reqs = load_csv('../scenario/requests.csv')
    res = load_csv('../scenario/resources.csv')
    gt = load_gt('../scenario/ground_truth.json')

    print("Running Baselines...")
    baseline_results = Baselines.run_all_baselines(reqs, res)

    print("Running Ablations...")
    ablation_results = Ablations.run_all_ablations(reqs, res)

    # Calculate metrics for all configurations
    print("Calculating Metrics...")
    all_results = {**baseline_results, **ablation_results}

    metrics_summary = {}
    for name, results in all_results.items():
        print(f"  Computing metrics for {name}...")
        calc = MetricsCalculator(results, gt, reqs, res)
        metrics_summary[name] = calc.get_summary()

    # Key comparison: Full Rescan vs ResQLink Incremental
    comparison = compare_configs(
        baseline_results['full_rescan'],
        ablation_results['D_full_resqlink'],
        reqs, res, gt
    )

    # Save results
    output = {
        'seed': seed,
        'metrics': metrics_summary,
        'key_comparison': {
            'full_rescan_vs_incremental': {
                'db_work_reduction_percent': comparison['db_work_reduction_percent'],
                'latency_improvement_ms': comparison['latency_improvement_ms'],
                'coverage_difference_percent': comparison['coverage_difference_percent'],
                'weighted_unmet_demand_difference': comparison['weighted_unmet_demand_difference']
            }
        }
    }

    os.makedirs('results', exist_ok=True)
    with open(f'results/summary_seed_{seed}.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Evaluation complete. Results saved to results/summary_seed_{seed}.json")
    return output

def run_multi_seed_evaluation(seeds=None):
    """Run evaluation across multiple seeds for statistical validity."""
    if seeds is None:
        seeds = [42, 123, 999, 1024, 2048]

    print(f"\n=== Multi-Seed Evaluation ({len(seeds)} seeds) ===")
    all_results = []

    for seed in seeds:
        result = run_evaluation(seed)
        all_results.append(result)

    # Aggregate statistics
    print("\n=== Aggregating Multi-Seed Results ===")
    agg = aggregate_results(all_results)

    with open('results/multi_seed_summary.json', 'w') as f:
        json.dump(agg, f, indent=2)

    print("Multi-seed results saved to results/multi_seed_summary.json")
    return agg

def aggregate_results(all_results):
    """Aggregate metrics across multiple seeds."""
    import numpy as np

    # Collect all metric names
    all_configs = set()
    for r in all_results:
        all_configs.update(r['metrics'].keys())

    aggregated = {'seeds': len(all_results), 'configs': {}}

    for config in all_configs:
        # Collect values for each metric
        metric_values = {}
        for r in all_results:
            if config in r['metrics']:
                for k, v in r['metrics'][config].items():
                    if isinstance(v, (int, float)):
                        if k not in metric_values:
                            metric_values[k] = []
                        metric_values[k].append(v)
                    elif isinstance(v, dict):
                        # Handle nested dicts (e.g., latency_ms)
                        for nk, nv in v.items():
                            if isinstance(nv, (int, float)):
                                key = f"{k}.{nk}"
                                if key not in metric_values:
                                    metric_values[key] = []
                                metric_values[key].append(nv)

        # Compute mean and std
        config_stats = {}
        for k, vals in metric_values.items():
            if vals:
                config_stats[k] = {
                    'mean': float(np.mean(vals)),
                    'std': float(np.std(vals)),
                    'min': float(np.min(vals)),
                    'max': float(np.max(vals)),
                    'values': vals
                }

        aggregated['configs'][config] = config_stats

    # Aggregate key comparison
    comp_key = 'full_rescan_vs_incremental'
    comp_metrics = {}
    for r in all_results:
        if 'key_comparison' in r and comp_key in r['key_comparison']:
            for k, v in r['key_comparison'][comp_key].items():
                if isinstance(v, (int, float)):
                    if k not in comp_metrics:
                        comp_metrics[k] = []
                    comp_metrics[k].append(v)

    aggregated['key_comparison'] = {}
    for k, vals in comp_metrics.items():
        if vals:
            aggregated['key_comparison'][k] = {
                'mean': float(np.mean(vals)),
                'std': float(np.std(vals)),
                'values': vals
            }

    return aggregated

if __name__ == '__main__':
    # Run single seed by default, or multi-seed if requested
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--multi-seed':
        run_multi_seed_evaluation()
    else:
        run_evaluation()