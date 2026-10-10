import threading
import time
import random
import json
import os
from runner import load_csv
from adapter import MockAdapter, EvaluationResult

class ConcurrencyTestHarness:
    """
    Concurrency benchmark harness for ResQLink.

    Tests multiple simultaneous matching/reservation attempts to verify
    0 double-allocations under contention.

    When Phase 4 is available, this will use the real DB engine with
    FOR UPDATE SKIP LOCKED and lease-based reservations.
    """

    def __init__(self, num_threads: int = 10, requests_per_thread: int = 20):
        self.num_threads = num_threads
        self.requests_per_thread = requests_per_thread
        self.results = []
        self.lock = threading.Lock()
        self.double_allocations = 0
        self.allocation_map = {}  # resource_id -> allocated quantities

    def run_mock_concurrency_test(self, requests, resources):
        """Run concurrency test using mock adapter with simulated contention."""
        print(f"Running mock concurrency test: {self.num_threads} threads, "
              f"{self.requests_per_thread} reqs/thread")

        # Filter to boat requests for focused test
        boat_requests = [r for r in requests if r['resource_type_needed'] == 'boat']
        boat_resources = [r for r in resources if r['resource_type'] == 'boat']

        if not boat_requests or not boat_resources:
            print("  No boat requests/resources for concurrency test")
            return {'double_allocations': 0, 'total_allocations': 0}

        # Select subset for test
        test_requests = boat_requests[:self.num_threads * self.requests_per_thread]
        test_resources = boat_resources

        # Shared resource state
        shared_resources = {r['resource_id']: float(r['quantity_available']) for r in test_resources}

        def worker(thread_id, req_subset):
            adapter = MockAdapter()
            local_results = []

            for req in req_subset:
                # Each request tries to allocate
                config = {'strategy': 'incremental', 'use_urgency': True, 'use_quantity': True}

                # Run matching (simplified - just check availability)
                start = time.time()
                best_res = None
                best_score = -float('inf')

                for res in test_resources:
                    if res['resource_type'] == req['resource_type_needed']:
                        avail = shared_resources.get(res['resource_id'], 0)
                        if avail > 0:
                            dist = ((float(req['lat']) - float(res['lat']))**2 +
                                   (float(req['lon']) - float(res['lon']))**2)**0.5 * 111
                            score = -dist + (1000 if req['urgency_level'] == 'critical' else 500)
                            if score > best_score:
                                best_score = score
                                best_res = res

                latency = (time.time() - start) * 1000

                if best_res:
                    rid = best_res['resource_id']
                    needed = float(req['quantity_requested'])

                    # CRITICAL SECTION - simulate atomic reservation
                    with self.lock:
                        current_avail = shared_resources.get(rid, 0)
                        if current_avail >= 1:
                            alloc = min(1, needed, current_avail)
                            shared_resources[rid] = current_avail - alloc

                            # Track for double-allocation detection
                            if rid not in self.allocation_map:
                                self.allocation_map[rid] = []
                            self.allocation_map[rid].append({
                                'thread': thread_id,
                                'request': req['request_id'],
                                'qty': alloc,
                                'time': time.time()
                            })

                            local_results.append(EvaluationResult(
                                request_id=req['request_id'],
                                matched=True,
                                resource_id=rid,
                                allocated_quantity=alloc,
                                match_latency_ms=latency
                            ))
                        else:
                            # Race condition: resource depleted between check and lock
                            self.double_allocations += 1
                            local_results.append(EvaluationResult(
                                request_id=req['request_id'],
                                matched=False,
                                match_latency_ms=latency
                            ))
                else:
                    local_results.append(EvaluationResult(
                        request_id=req['request_id'],
                        matched=False,
                        match_latency_ms=latency
                    ))

            with self.lock:
                self.results.extend(local_results)

        # Split requests among threads
        threads = []
        chunk_size = len(test_requests) // self.num_threads
        for i in range(self.num_threads):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size if i < self.num_threads - 1 else len(test_requests)
            thread_reqs = test_requests[start_idx:end_idx]

            t = threading.Thread(target=worker, args=(i, thread_reqs))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Analyze results
        total_allocs = sum(len(v) for v in self.allocation_map.values())
        double_allocs = sum(1 for v in self.allocation_map.values() if len(v) > 1)

        print(f"  Total allocations: {total_allocs}")
        print(f"  Double allocations detected: {double_allocs}")
        print(f"  Resources with contention: {sum(1 for v in self.allocation_map.values() if len(v) > 1)}")

        return {
            'total_allocations': total_allocs,
            'double_allocations': double_allocs,
            'contended_resources': sum(1 for v in self.allocation_map.values() if len(v) > 1),
            'allocation_details': self.allocation_map
        }

def run_real_db_concurrency_test():
    """
    Placeholder for real DB concurrency test (Phase 4).

    When Phase 4 is integrated, this will:
    1. Spawn N threads/clients
    2. Each executes: SELECT ... FOR UPDATE SKIP LOCKED on reservation table
    3. Verify 0 double-allocations via ledger balance check
    4. Measure contention latency
    """
    print("=" * 60)
    print("REAL DB CONCURRENCY TEST - HARNESS READY")
    print("=" * 60)
    print("RUNTIME RESULTS PENDING: Phase 4 transactional DB implementation")
    print("is not yet available.")
    print("")
    print("When Phase 4 is ready, this test will:")
    print("  1. Spawn N concurrent workers (configurable)")
    print("  2. Each attempts atomic reservation via FOR UPDATE SKIP LOCKED")
    print("  3. Verify 0 double-allocations via ledger audit")
    print("  4. Measure p99 latency under contention")
    print("  5. Test lease expiration and re-matching")
    print("")
    print("Expected invariant: double_allocations == 0")
    return {'status': 'harness_ready', 'phase4_required': True}

if __name__ == '__main__':
    print("Concurrency Evaluation Harness")
    print("-" * 40)

    # Run mock test
    reqs = load_csv('../scenario/requests.csv')
    res = load_csv('../scenario/resources.csv')

    harness = ConcurrencyTestHarness(num_threads=10, requests_per_thread=10)
    mock_results = harness.run_mock_concurrency_test(reqs, res)

    # Save results
    os.makedirs('results', exist_ok=True)
    with open('results/concurrency_mock.json', 'w') as f:
        json.dump(mock_results, f, indent=2, default=str)

    print("\nMock results saved to results/concurrency_mock.json")

    # Show real test status
    print()
    run_real_db_concurrency_test()