from adapter import MockAdapter

class Baselines:
    """
    Conventional baseline matching strategies for fair comparison.

    The most important comparison is:
    FULL RESCAN vs. RESQLINK INCREMENTAL RE-MATCHING

    Both operate on the same scenario and equivalent inputs.
    No intentionally weak baselines.
    """

    @staticmethod
    def run_distance_only(requests, resources):
        """A. Distance-only / nearest-first baseline."""
        adapter = MockAdapter()
        return adapter.run(requests, resources, {
            'strategy': 'full_rescan',
            'use_urgency': False,
            'use_quantity': False,
            'use_confidence': False,
            'use_pool_pressure': False,
            'use_hazard': False
        })

    @staticmethod
    def run_urgency_distance(requests, resources):
        """B. Urgency + distance conventional strategy (standard priority queue)."""
        adapter = MockAdapter()
        return adapter.run(requests, resources, {
            'strategy': 'full_rescan',
            'use_urgency': True,
            'use_quantity': False,
            'use_confidence': False,
            'use_pool_pressure': False,
            'use_hazard': False
        })

    @staticmethod
    def run_urgency_distance_quantity(requests, resources):
        """C. Urgency + distance + quantity/partial allocation (more realistic conventional)."""
        adapter = MockAdapter()
        return adapter.run(requests, resources, {
            'strategy': 'full_rescan',
            'use_urgency': True,
            'use_quantity': True,
            'use_confidence': False,
            'use_pool_pressure': False,
            'use_hazard': False
        })

    @staticmethod
    def run_first_available(requests, resources):
        """D. First-available / random baseline."""
        import random
        shuffled = list(resources)
        random.shuffle(shuffled)
        adapter = MockAdapter()
        return adapter.run(requests, shuffled, {
            'strategy': 'full_rescan',
            'use_urgency': False,
            'use_quantity': False,
            'use_confidence': False,
            'use_pool_pressure': False,
            'use_hazard': False
        })

    @staticmethod
    def run_full_rescan(requests, resources):
        """
        E. Full-rescan version with all features enabled.
        This is the conventional "full ResQLink" without incremental optimization.
        """
        adapter = MockAdapter()
        return adapter.run(requests, resources, {
            'strategy': 'full_rescan',
            'use_urgency': True,
            'use_quantity': True,
            'use_confidence': True,
            'use_pool_pressure': True,
            'use_hazard': True
        })

    @staticmethod
    def run_all_baselines(requests, resources):
        """Run all baseline configurations and return results dict."""
        import copy
        reqs = copy.deepcopy(requests)
        res = copy.deepcopy(resources)

        return {
            'distance_only': Baselines.run_distance_only(reqs, res),
            'urgency_distance': Baselines.run_urgency_distance(reqs, res),
            'urgency_distance_quantity': Baselines.run_urgency_distance_quantity(reqs, res),
            'first_available': Baselines.run_first_available(reqs, res),
            'full_rescan': Baselines.run_full_rescan(reqs, res),
        }