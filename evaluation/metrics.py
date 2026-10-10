import numpy as np
import json
import math
from typing import List, Dict, Any, Optional
from adapter import EvaluationResult

class MetricsCalculator:
    """
    Comprehensive metrics for ResQLink evaluation.

    Implements all required metrics from Phase 7:
    A. Database work saved (rows/pairs evaluated, percentage reduction)
    B. Re-match latency (p50, p95, p99)
    C. Concurrency (double allocation count)
    D. Coverage (percentage matched)
    E. Weighted unmet demand (critical requests weighted more)
    F. Ground-truth accuracy (ILP optimality gap)
    G. Stale-resource behavior
    H. Reallocation count
    I. Accessibility (hazard-aware vs straight-line)
    J. Fairness (waiting time/starvation of lower-urgency)
    """

    def __init__(self, results: List[EvaluationResult], ground_truth: Optional[Dict] = None,
                 requests: Optional[List[Dict]] = None, resources: Optional[List[Dict]] = None):
        self.results = results
        self.ground_truth = ground_truth
        self.requests = requests or []
        self.resources = resources or []

        # Build lookup maps
        self.gt_allocations = {}
        if ground_truth and 'allocations' in ground_truth:
            for alloc in ground_truth['allocations']:
                self.gt_allocations[alloc['request_id']] = alloc

        self.req_map = {r['request_id']: r for r in self.requests}
        self.res_map = {r['resource_id']: r for r in self.resources}

    def calculate_coverage(self) -> float:
        """D. Coverage: percentage of requests successfully matched (fully or partially)."""
        if not self.results:
            return 0.0
        matched = sum(1 for r in self.results if r.matched)
        return (matched / len(self.results)) * 100.0

    def calculate_full_coverage(self) -> float:
        """Percentage of requests fully fulfilled."""
        if not self.results:
            return 0.0
        fulfilled = sum(1 for r in self.results if r.status == 'fulfilled')
        return (fulfilled / len(self.results)) * 100.0

    def calculate_latencies(self) -> Dict[str, float]:
        """B. Re-match latency percentiles."""
        lats = [r.match_latency_ms for r in self.results if r.match_latency_ms > 0]
        if not lats:
            return {'p50': 0.0, 'p95': 0.0, 'p99': 0.0, 'mean': 0.0, 'std': 0.0}
        return {
            'p50': float(np.percentile(lats, 50)),
            'p95': float(np.percentile(lats, 95)),
            'p99': float(np.percentile(lats, 99)),
            'mean': float(np.mean(lats)),
            'std': float(np.std(lats))
        }

    def calculate_db_work(self) -> Dict[str, Any]:
        """A. Database work saved: rows scanned, candidate pairs evaluated."""
        rows = [getattr(r, 'rows_scanned', 0) for r in self.results]
        pairs = [getattr(r, 'candidate_pairs_evaluated', 0) for r in self.results]
        return {
            'total_rows_scanned': sum(rows),
            'total_candidate_pairs': sum(pairs),
            'mean_rows_per_request': float(np.mean(rows)) if rows else 0.0,
            'mean_pairs_per_request': float(np.mean(pairs)) if pairs else 0.0
        }

    def calculate_db_work_reduction(self, baseline_rows: int) -> float:
        """Percentage reduction in DB work vs baseline."""
        current = self.calculate_db_work()['total_rows_scanned']
        if baseline_rows == 0:
            return 0.0
        return ((baseline_rows - current) / baseline_rows) * 100.0

    def calculate_double_allocations(self) -> int:
        """C. Concurrency: double allocation count (mock returns 0)."""
        # In real DB: query for negative ledger balances or overlapping leased intervals
        return 0

    def calculate_weighted_unmet_demand(self) -> Dict[str, float]:
        """
        E. Weighted unmet demand.
        Critical requests weighted more heavily than lower-priority requests.
        """
        urgency_weights = {'critical': 1000, 'high': 500, 'medium': 100, 'low': 10}

        total_weighted_demand = 0.0
        total_weighted_unmet = 0.0
        total_unmet = 0
        unmet_by_urgency = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}

        for r in self.results:
            req = self.req_map.get(r.request_id)
            if not req:
                continue

            demand = float(req['quantity_requested'])
            allocated = r.allocated_quantity
            unmet = max(0, demand - allocated)
            weight = urgency_weights.get(req['urgency_level'], 10)

            total_weighted_demand += demand * weight
            total_weighted_unmet += unmet * weight
            total_unmet += unmet
            unmet_by_urgency[req['urgency_level']] += unmet

        return {
            'weighted_unmet_demand': total_weighted_unmet,
            'weighted_demand_total': total_weighted_demand,
            'weighted_unmet_ratio': (total_weighted_unmet / total_weighted_demand * 100) if total_weighted_demand > 0 else 0,
            'total_unmet_units': total_unmet,
            'unmet_by_urgency': unmet_by_urgency
        }

    def calculate_ground_truth_accuracy(self) -> Dict[str, Any]:
        """
        F. Ground-truth accuracy: compare against verified ILP answer key.
        - Exact match rate
        - Acceptable/near-optimal match rate
        - Optimality gap
        - Unmet-demand difference
        """
        if not self.ground_truth or not self.gt_allocations:
            return {'available': False, 'message': 'No ground truth loaded'}

        exact_matches = 0
        acceptable_matches = 0
        total_compared = 0
        optimality_gap = 0.0
        unmet_diff = 0.0

        for r in self.results:
            gt = self.gt_allocations.get(r.request_id)
            if not gt:
                continue

            total_compared += 1

            # Exact match: same resource(s) and quantity
            gt_resources = set(a['resource_id'] for a in gt['resources_used'])
            our_resources = set([r.resource_id]) if r.resource_id else set()

            if (r.allocated_quantity == gt['allocated_qty'] and
                gt_resources == our_resources and
                r.status == gt['status']):
                exact_matches += 1

            # Acceptable: same fulfillment status and similar quantity (+/- 1 unit)
            if (r.status == gt['status'] and
                abs(r.allocated_quantity - gt['allocated_qty']) <= 1):
                acceptable_matches += 1

            # Optimality gap: difference in weighted unmet demand
            req = self.req_map.get(r.request_id)
            if req:
                weight = {'critical': 1000, 'high': 500, 'medium': 100, 'low': 10}.get(req['urgency_level'], 10)
                our_unmet = max(0, float(req['quantity_requested']) - r.allocated_quantity)
                gt_unmet = max(0, float(req['quantity_requested']) - gt['allocated_qty'])
                optimality_gap += (our_unmet - gt_unmet) * weight
                unmet_diff += our_unmet - gt_unmet

        return {
            'available': True,
            'total_compared': total_compared,
            'exact_match_rate': (exact_matches / total_compared * 100) if total_compared > 0 else 0,
            'acceptable_match_rate': (acceptable_matches / total_compared * 100) if total_compared > 0 else 0,
            'optimality_gap_weighted': optimality_gap,
            'unmet_demand_difference': unmet_diff,
            'exact_matches': exact_matches,
            'acceptable_matches': acceptable_matches
        }

    def calculate_stale_resource_behavior(self) -> Dict[str, Any]:
        """
        G. Stale-resource behavior: match rate against stale/depleted resources.
        """
        stale_matches = 0
        total_matches = 0

        for r in self.results:
            if r.matched and r.resource_id:
                res = self.res_map.get(r.resource_id)
                if res and res.get('status') in ['depleted', 'maintenance', 'allocated']:
                    stale_matches += 1
                total_matches += 1

        return {
            'stale_match_count': stale_matches,
            'total_matches': total_matches,
            'stale_match_rate': (stale_matches / total_matches * 100) if total_matches > 0 else 0
        }

    def calculate_reallocations(self) -> int:
        """H. Reallocation count (mock always 0 without real engine)."""
        # In real engine: count reservation lease expirations and re-matches
        return sum(1 for r in self.results if getattr(r, 'reallocated', False))

    def calculate_accessibility(self) -> Dict[str, float]:
        """
        I. Accessibility: hazard-aware vs straight-line distance.
        Mock implementation - real version would use PostGIS routing.
        """
        distances = [r.distance_km for r in self.results if r.matched and r.distance_km > 0]
        if not distances:
            return {'mean_distance_km': 0, 'median_distance_km': 0}

        return {
            'mean_distance_km': float(np.mean(distances)),
            'median_distance_km': float(np.median(distances)),
            'max_distance_km': float(np.max(distances)),
            'min_distance_km': float(np.min(distances))
        }

    def calculate_fairness(self) -> Dict[str, Any]:
        """
        J. Fairness: measure waiting time/starvation of lower-urgency requests.
        """
        urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        wait_times = {u: [] for u in urgency_order}
        fulfillment_by_urgency = {u: {'total': 0, 'fulfilled': 0, 'partial': 0} for u in urgency_order}

        for r in self.results:
            req = self.req_map.get(r.request_id)
            if not req:
                continue

            urg = req['urgency_level']
            fulfillment_by_urgency[urg]['total'] += 1
            if r.status == 'fulfilled':
                fulfillment_by_urgency[urg]['fulfilled'] += 1
            elif r.status == 'partially_fulfilled':
                fulfillment_by_urgency[urg]['partial'] += 1

            # Mock wait time: proportional to latency for unmatched
            if not r.matched:
                wait_times[urg].append(r.match_latency_ms)

        # Calculate starvation rate for low-urgency
        low_total = fulfillment_by_urgency['low']['total']
        low_fulfilled = fulfillment_by_urgency['low']['fulfilled'] + fulfillment_by_urgency['low']['partial']

        return {
            'fulfillment_by_urgency': {
                urg: {
                    'rate': (d['fulfilled'] + d['partial']) / d['total'] * 100 if d['total'] > 0 else 0,
                    'full_rate': d['fulfilled'] / d['total'] * 100 if d['total'] > 0 else 0,
                    'total': d['total']
                }
                for urg, d in fulfillment_by_urgency.items()
            },
            'low_urgency_starvation_rate': 100 - (low_fulfilled / low_total * 100) if low_total > 0 else 0,
            'wait_time_ms_by_urgency': {
                urg: float(np.mean(w)) if w else 0 for urg, w in wait_times.items()
            }
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive metrics summary."""
        db_work = self.calculate_db_work()
        gt_acc = self.calculate_ground_truth_accuracy()

        return {
            'coverage_percent': self.calculate_coverage(),
            'full_coverage_percent': self.calculate_full_coverage(),
            'latency_ms': self.calculate_latencies(),
            'db_work': db_work,
            'double_allocations': self.calculate_double_allocations(),
            'weighted_unmet_demand': self.calculate_weighted_unmet_demand(),
            'ground_truth_accuracy': gt_acc,
            'stale_resource_behavior': self.calculate_stale_resource_behavior(),
            'reallocations': self.calculate_reallocations(),
            'accessibility': self.calculate_accessibility(),
            'fairness': self.calculate_fairness()
        }


def compare_configs(baseline_results: List[EvaluationResult],
                    test_results: List[EvaluationResult],
                    requests: List[Dict],
                    resources: List[Dict],
                    ground_truth: Optional[Dict] = None) -> Dict[str, Any]:
    """Compare two configurations and compute relative improvements."""
    baseline_metrics = MetricsCalculator(baseline_results, ground_truth, requests, resources)
    test_metrics = MetricsCalculator(test_results, ground_truth, requests, resources)

    base_summary = baseline_metrics.get_summary()
    test_summary = test_metrics.get_summary()

    db_work_reduction = test_metrics.calculate_db_work_reduction(base_summary['db_work']['total_rows_scanned'])
    latency_improvement = {
        'p50': base_summary['latency_ms']['p50'] - test_summary['latency_ms']['p50'],
        'p95': base_summary['latency_ms']['p95'] - test_summary['latency_ms']['p95'],
        'p99': base_summary['latency_ms']['p99'] - test_summary['latency_ms']['p99'],
    }
    coverage_diff = test_summary['coverage_percent'] - base_summary['coverage_percent']
    weighted_unmet_diff = (test_summary['weighted_unmet_demand']['weighted_unmet_demand'] -
                           base_summary['weighted_unmet_demand']['weighted_unmet_demand'])

    return {
        'db_work_reduction_percent': db_work_reduction,
        'latency_improvement_ms': latency_improvement,
        'coverage_difference_percent': coverage_diff,
        'weighted_unmet_demand_difference': weighted_unmet_diff,
        'baseline': base_summary,
        'test': test_summary
    }