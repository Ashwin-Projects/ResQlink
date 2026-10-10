import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import json
import numpy as np
import os

def generate_charts():
    """Generate 2-3 clear charts for DBTHON demonstration."""
    try:
        with open('results/multi_seed_summary.json', 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        # Fallback to single seed
        try:
            with open('results/summary_seed_42.json', 'r') as f:
                data = json.load(f)
                data = {'configs': data['metrics'], 'key_comparison': data['key_comparison']}
        except FileNotFoundError:
            print("Run runner.py first to generate results.")
            return

    os.makedirs('charts', exist_ok=True)
    configs = data.get('configs', {})

    # Chart 1: Database Work - Full Rescan vs Incremental
    plot_db_work(configs)

    # Chart 2: Match Latency - Full Rescan vs Incremental
    plot_latency(configs)

    # Chart 3: Coverage & Weighted Unmet Demand - Conventional vs ResQLink
    plot_coverage_unmet(configs)

    # Chart 4: Ablation Study (all 8 configurations)
    plot_ablation_study(configs)

    # Chart 5: Multi-seed variability (if available)
    if 'seeds' in data and data['seeds'] > 1:
        plot_multi_seed_variability(data)

    print("Charts generated in charts/ directory.")

def plot_db_work(configs):
    """Chart 1: Database work (rows evaluated) comparison."""
    plt.figure(figsize=(10, 6))

    # Key comparison: Full Rescan vs Incremental
    baseline_rows = configs.get('full_rescan', {}).get('db_work.total_rows_scanned', {}).get('mean', 0)
    incremental_rows = configs.get('D_full_resqlink', {}).get('db_work.total_rows_scanned', {}).get('mean', 0)

    # If multi-seed not available, use single values
    if baseline_rows == 0:
        baseline_rows = configs.get('full_rescan', {}).get('db_work', {}).get('total_rows_scanned', 0)
    if incremental_rows == 0:
        incremental_rows = configs.get('D_full_resqlink', {}).get('db_work', {}).get('total_rows_scanned', 0)

    labels = ['Full Rescan\n(Conventional)', 'ResQLink\nIncremental']
    values = [baseline_rows, incremental_rows]
    colors = ['#e74c3c', '#2ecc71']

    bars = plt.bar(labels, values, color=colors, edgecolor='black', linewidth=1.5, width=0.6)

    # Add value labels on bars
    for bar, val in zip(bars, values):
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.01,
                f'{int(val):,}', ha='center', va='bottom', fontsize=12, fontweight='bold')

    # Add reduction percentage
    if baseline_rows > 0:
        reduction = (baseline_rows - incremental_rows) / baseline_rows * 100
        plt.text(0.5, max(values) * 0.8, f'{reduction:.1f}% reduction',
                ha='center', fontsize=14, fontweight='bold', color='#2c3e50',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8))

    plt.title('Database Work: Rows Evaluated per Matching Run', fontsize=14, fontweight='bold', pad=20)
    plt.ylabel('Rows Scanned / Evaluated', fontsize=12)
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig('charts/db_work.png', dpi=150, bbox_inches='tight')
    plt.close()

def plot_latency(configs):
    """Chart 2: Match Latency p50/p95/p99 comparison."""
    plt.figure(figsize=(10, 6))

    baseline = configs.get('full_rescan', {})
    incremental = configs.get('D_full_resqlink', {})

    # Get latency percentiles
    base_p50 = baseline.get('latency_ms.p50', {}).get('mean', baseline.get('latency_ms', {}).get('p50', 0))
    base_p95 = baseline.get('latency_ms.p95', {}).get('mean', baseline.get('latency_ms', {}).get('p95', 0))
    base_p99 = baseline.get('latency_ms.p99', {}).get('mean', baseline.get('latency_ms', {}).get('p99', 0))

    inc_p50 = incremental.get('latency_ms.p50', {}).get('mean', incremental.get('latency_ms', {}).get('p50', 0))
    inc_p95 = incremental.get('latency_ms.p95', {}).get('mean', incremental.get('latency_ms', {}).get('p95', 0))
    inc_p99 = incremental.get('latency_ms.p99', {}).get('mean', incremental.get('latency_ms', {}).get('p99', 0))

    # Also include other baselines for context
    baseline_names = ['Full Rescan', 'ResQLink\nIncremental']
    x = np.arange(len(baseline_names))
    width = 0.25

    p50_vals = [base_p50, inc_p50]
    p95_vals = [base_p95, inc_p95]
    p99_vals = [base_p99, inc_p99]

    bars1 = plt.bar(x - width, p50_vals, width, label='p50', color='#3498db', edgecolor='black')
    bars2 = plt.bar(x, p95_vals, width, label='p95', color='#f39c12', edgecolor='black')
    bars3 = plt.bar(x + width, p99_vals, width, label='p99', color='#e74c3c', edgecolor='black')

    # Add value labels
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                plt.text(bar.get_x() + bar.get_width()/2, h + 0.05,
                        f'{h:.1f}', ha='center', va='bottom', fontsize=10)

    plt.title('Match Latency Percentiles', fontsize=14, fontweight='bold', pad=20)
    plt.ylabel('Latency (ms)', fontsize=12)
    plt.xticks(x, baseline_names)
    plt.legend()
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig('charts/latency_p95.png', dpi=150, bbox_inches='tight')
    plt.close()

def plot_coverage_unmet(configs):
    """Chart 3: Coverage and Weighted Unmet Demand comparison."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Subplot 1: Coverage
    baseline_cov = configs.get('full_rescan', {}).get('coverage_percent', {}).get('mean',
                        configs.get('full_rescan', {}).get('coverage_percent', 0))
    inc_cov = configs.get('D_full_resqlink', {}).get('coverage_percent', {}).get('mean',
                        configs.get('D_full_resqlink', {}).get('coverage_percent', 0))

    # Also show distance-only baseline
    dist_cov = configs.get('distance_only', {}).get('coverage_percent', {}).get('mean',
                       configs.get('distance_only', {}).get('coverage_percent', 0))
    urg_cov = configs.get('urgency_distance', {}).get('coverage_percent', {}).get('mean',
                        configs.get('urgency_distance', {}).get('coverage_percent', 0))

    labels = ['Distance Only', 'Urgency+Dist', 'Full Rescan\n(Conventional)', 'ResQLink\nIncremental']
    values = [dist_cov, urg_cov, baseline_cov, inc_cov]
    colors = ['#95a5a6', '#f39c12', '#e74c3c', '#2ecc71']

    bars = ax1.bar(labels, values, color=colors, edgecolor='black', linewidth=1.5)
    for bar, val in zip(bars, values):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax1.set_title('Request Coverage (% Matched)', fontsize=13, fontweight='bold', pad=15)
    ax1.set_ylabel('Coverage %', fontsize=11)
    ax1.set_ylim(0, max(values) * 1.2 if max(values) > 0 else 100)
    ax1.grid(axis='y', alpha=0.3)

    # Subplot 2: Weighted Unmet Demand
    base_unmet = configs.get('full_rescan', {}).get('weighted_unmet_demand.weighted_unmet_demand', {}).get('mean',
                         configs.get('full_rescan', {}).get('weighted_unmet_demand', {}).get('weighted_unmet_demand', 0))
    inc_unmet = configs.get('D_full_resqlink', {}).get('weighted_unmet_demand.weighted_unmet_demand', {}).get('mean',
                         configs.get('D_full_resqlink', {}).get('weighted_unmet_demand', {}).get('weighted_unmet_demand', 0))
    dist_unmet = configs.get('distance_only', {}).get('weighted_unmet_demand.weighted_unmet_demand', {}).get('mean',
                         configs.get('distance_only', {}).get('weighted_unmet_demand', {}).get('weighted_unmet_demand', 0))
    urg_unmet = configs.get('urgency_distance', {}).get('weighted_unmet_demand.weighted_unmet_demand', {}).get('mean',
                         configs.get('urgency_distance', {}).get('weighted_unmet_demand', {}).get('weighted_unmet_demand', 0))

    values2 = [dist_unmet, urg_unmet, base_unmet, inc_unmet]
    bars2 = ax2.bar(labels, values2, color=colors, edgecolor='black', linewidth=1.5)
    for bar, val in zip(bars2, values2):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values2)*0.01,
                f'{val:,.0f}', ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax2.set_title('Weighted Unmet Demand\n(Critical=1000, High=500, Med=100, Low=10)', fontsize=13, fontweight='bold', pad=15)
    ax2.set_ylabel('Weighted Unmet Units', fontsize=11)
    ax2.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig('charts/coverage_unmet.png', dpi=150, bbox_inches='tight')
    plt.close()

def plot_ablation_study(configs):
    """Chart 4: Ablation study - all 8 configurations."""
    plt.figure(figsize=(14, 8))

    ablation_order = [
        'A_distance_only', 'B_distance_urgency', 'C_distance_quantity',
        'D_full_resqlink', 'E_no_confidence', 'F_no_pool_pressure',
        'G_no_hazard', 'H_full_rescan'
    ]

    labels = ['A: Distance\nOnly', 'B: Dist+\nUrgency', 'C: Dist+\nQuantity',
              'D: Full\nResQLink', 'E: No\nConfidence', 'F: No Pool\nPressure',
              'G: No\nHazard', 'H: Full\nRescan']

    # Coverage
    coverage_vals = []
    for cfg in ablation_order:
        v = configs.get(cfg, {}).get('coverage_percent', {}).get('mean',
                configs.get(cfg, {}).get('coverage_percent', 0))
        coverage_vals.append(v)

    # Weighted unmet
    unmet_vals = []
    for cfg in ablation_order:
        v = configs.get(cfg, {}).get('weighted_unmet_demand.weighted_unmet_demand', {}).get('mean',
                configs.get(cfg, {}).get('weighted_unmet_demand', {}).get('weighted_unmet_demand', 0))
        unmet_vals.append(v)

    # DB Work
    db_vals = []
    for cfg in ablation_order:
        v = configs.get(cfg, {}).get('db_work.total_rows_scanned', {}).get('mean',
                configs.get(cfg, {}).get('db_work', {}).get('total_rows_scanned', 0))
        db_vals.append(v)

    x = np.arange(len(labels))
    width = 0.25

    # Normalize for grouped bar chart
    max_cov = max(coverage_vals) if coverage_vals else 1
    max_unmet = max(unmet_vals) if unmet_vals else 1
    max_db = max(db_vals) if db_vals else 1

    # Use twin axis for different scales
    ax1 = plt.gca()
    bars1 = ax1.bar(x - width, [v/max_cov*100 for v in coverage_vals], width,
                    label='Coverage %', color='#2ecc71', edgecolor='black')
    bars2 = ax1.bar(x, [v/max_unmet*100 for v in unmet_vals], width,
                    label='Weighted Unmet %', color='#e74c3c', edgecolor='black')

    ax2 = ax1.twinx()
    bars3 = ax2.bar(x + width, [v/max_db*100 for v in db_vals], width,
                    label='DB Work %', color='#3498db', edgecolor='black')

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel('Normalized Coverage / Unmet (%)', fontsize=11)
    ax2.set_ylabel('Normalized DB Work (%)', fontsize=11)
    ax1.set_title('Ablation Study: Impact of Each Component', fontsize=14, fontweight='bold', pad=20)

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right')

    ax1.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig('charts/ablation_study.png', dpi=150, bbox_inches='tight')
    plt.close()

def plot_multi_seed_variability(data):
    """Chart 5: Multi-seed variability with error bars."""
    plt.figure(figsize=(10, 6))

    configs = data.get('configs', {})
    key_configs = ['full_rescan', 'D_full_resqlink', 'distance_only', 'urgency_distance']
    labels = ['Full Rescan', 'ResQLink Inc.', 'Distance Only', 'Urgency+Dist']

    means = []
    stds = []

    for cfg in key_configs:
        if cfg in configs:
            lat = configs[cfg].get('latency_ms.p95', {})
            means.append(lat.get('mean', 0))
            stds.append(lat.get('std', 0))
        else:
            means.append(0)
            stds.append(0)

    x = np.arange(len(labels))
    colors = ['#e74c3c', '#2ecc71', '#95a5a6', '#f39c12']

    bars = plt.bar(x, means, yerr=stds, capsize=10, color=colors, edgecolor='black',
                   linewidth=1.5, error_kw={'linewidth': 2})

    for bar, mean, std in zip(bars, means, stds):
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + std + 0.1,
                f'{mean:.1f}±{std:.1f}', ha='center', va='bottom', fontsize=11, fontweight='bold')

    plt.title(f'p95 Latency Across {data.get("seeds", 5)} Random Seeds', fontsize=14, fontweight='bold', pad=20)
    plt.ylabel('Latency (ms)', fontsize=12)
    plt.xticks(x, labels)
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig('charts/multi_seed_variability.png', dpi=150, bbox_inches='tight')
    plt.close()

if __name__ == '__main__':
    generate_charts()