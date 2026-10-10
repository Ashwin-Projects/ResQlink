import time
import math
import copy
import random
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

@dataclass
class EvaluationResult:
    request_id: str
    matched: bool
    resource_id: Optional[str] = None
    allocated_quantity: float = 0.0
    match_latency_ms: float = 0.0
    distance_km: float = 0.0
    score: float = 0.0
    status: str = 'unfulfilled'
    # Metadata for metrics
    rows_scanned: int = 0
    candidate_pairs_evaluated: int = 0
    urgency_compliance: bool = False
    is_stale_resource: bool = False
    reallocated: bool = False
    wait_time_hours: float = 0.0

class MatcherAdapter:
    """Base interface for matching engines (Mock or Real DB)"""
    def run(self, requests: List[Dict], resources: List[Dict], configuration: Dict[str, Any]) -> List[EvaluationResult]:
        raise NotImplementedError()

    def get_name(self) -> str:
        raise NotImplementedError()

def get_dist(req: Dict, res: Dict) -> float:
    """Calculate distance in km between request and resource."""
    return math.hypot(float(req['lat']) - float(res['lat']), float(req['lon']) - float(res['lon'])) * 111.0

def get_urgency_weight(level: str) -> int:
    weights = {'critical': 1000, 'high': 500, 'medium': 100, 'low': 10}
    return weights.get(level, 10)

class MockAdapter(MatcherAdapter):
    """
    Mock adapter simulating the matcher behavior for Phase 7 evaluation.
    Uses Python heuristics to imitate different configurations since Phase 4 is pending.
    Supports incremental vs full-rescan strategies and various feature flags.
    """
    def get_name(self) -> str:
        return "MockAdapter"

    def run(self, requests: List[Dict], resources: List[Dict], configuration: Dict[str, Any]) -> List[EvaluationResult]:
        results = []
        resources_copy = copy.deepcopy(resources)
        strategy = configuration.get('strategy', 'full_rescan')

        # Sort requests by urgency and time (critical first, then by requested_at)
        urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        sorted_requests = sorted(requests, key=lambda r: (urgency_order.get(r['urgency_level'], 3), r.get('requested_at', '')))

        for req in sorted_requests:
            start_t = time.time()
            best_res = None
            best_score = -float('inf')
            candidate_pairs = 0
            rows_scanned = 0

            # Determine candidate resources based on strategy
            if strategy == 'incremental':
                # Incremental: only check resources in dependent pools
                # Mock: simulate by filtering to resources of matching type in nearby zones
                matching_type = [r for r in resources_copy if r['resource_type'] == req['resource_type_needed']]
                # Further filter: simulate pool dependency - only resources not yet heavily allocated
                candidates = [r for r in matching_type if float(r['quantity_available']) > 0]
                # Simulate pool index reducing candidates by ~80%
                candidates = candidates[:max(1, len(candidates) // 5)]
            else:
                # Full rescan: check all resources
                candidates = [r for r in resources_copy if r['resource_type'] == req['resource_type_needed'] and float(r['quantity_available']) > 0]

            rows_scanned = len(candidates)

            # Check hazard accessibility if enabled
            if configuration.get('use_hazard', False):
                # Mock: filter out resources in hazard zones (simplified)
                # In reality, this would check PostGIS ST_Intersects with hazard_area
                pass  # For mock, we skip actual geometry check

            for res in candidates:
                candidate_pairs += 1
                dist = get_dist(req, res)

                # Base score: negative distance (closer is better)
                score = -dist

                if configuration.get('use_urgency', False):
                    score += get_urgency_weight(req['urgency_level'])

                if configuration.get('use_quantity', False):
                    # Prefer resources that can fulfill more of the request
                    avail = float(res['quantity_available'])
                    needed = float(req['quantity_requested'])
                    score += min(avail, needed) * 10

                if configuration.get('use_confidence', False):
                    # Mock confidence: resources with higher availability get slight boost
                    avail_ratio = float(res['quantity_available']) / max(1, float(res['quantity_total']))
                    score += avail_ratio * 50

                if configuration.get('use_pool_pressure', False):
                    # Mock pool pressure: penalize resources with many pending requests
                    # In reality, this would come from request_pool_dependency table
                    pass  # Simplified for mock

                if score > best_score:
                    best_score = score
                    best_res = res

            latency = (time.time() - start_t) * 1000

            # Add simulated database latency
            if strategy == 'incremental':
                latency += 1.0  # ~1ms for incremental index hit
            else:
                latency += 5.0  # ~5ms for full table scan mock

            if best_res:
                alloc = min(float(best_res['quantity_available']), float(req['quantity_requested']))
                best_res['quantity_available'] = float(best_res['quantity_available']) - alloc

                status = 'fulfilled' if alloc >= float(req['quantity_requested']) else 'partially_fulfilled'
                urgency_compliant = req['urgency_level'] in ['critical', 'high'] and alloc > 0

                results.append(EvaluationResult(
                    request_id=req['request_id'],
                    matched=True,
                    resource_id=best_res['resource_id'],
                    allocated_quantity=alloc,
                    match_latency_ms=latency,
                    distance_km=get_dist(req, best_res),
                    score=best_score,
                    status=status,
                    rows_scanned=rows_scanned,
                    candidate_pairs_evaluated=candidate_pairs,
                    urgency_compliance=urgency_compliant
                ))
            else:
                results.append(EvaluationResult(
                    request_id=req['request_id'],
                    matched=False,
                    match_latency_ms=latency,
                    status='unfulfilled',
                    rows_scanned=rows_scanned,
                    candidate_pairs_evaluated=candidate_pairs
                ))

        return results

class RealResQLinkAdapter(MatcherAdapter):
    """Adapter for real ResQLink PostgreSQL/FastAPI matching engine."""
    def get_name(self) -> str:
        return "RealResQLinkAdapter"

    def run(self, requests: List[Dict], resources: List[Dict], configuration: Dict[str, Any]) -> List[EvaluationResult]:
        # TODO: Implement PostgreSQL/FastAPI client once Phase 4 is integrated.
        raise NotImplementedError("Real DB Matching Engine not yet available (Phase 4 pending).")