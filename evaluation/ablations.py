from adapter import MockAdapter

class Ablations:
    """
    Implements Ablation studies A-H from Phase 7 plan.

    Ablation Table:
    A. distance only
    B. distance + urgency
    C. distance + quantity / partial allocation
    D. full ResQLink (all features, incremental)
    E. ResQLink without confidence
    F. ResQLink without pool pressure
    G. ResQLink without hazard accessibility
    H. ResQLink using full re-scan instead of incremental re-matching
    """

    @staticmethod
    def get_base_config():
        """Base ResQLink incremental configuration with all features."""
        return {
            'strategy': 'incremental',
            'use_urgency': True,
            'use_quantity': True,
            'use_confidence': True,
            'use_pool_pressure': True,
            'use_hazard': True
        }

    @staticmethod
    def run_ablation(requests, resources, config_name: str):
        """Run a specific ablation configuration."""
        adapter = MockAdapter()
        base_config = Ablations.get_base_config()

        configs = {
            'A_distance_only': {
                **base_config,
                'use_urgency': False,
                'use_quantity': False,
                'use_confidence': False,
                'use_pool_pressure': False,
                'use_hazard': False
            },
            'B_distance_urgency': {
                **base_config,
                'use_quantity': False,
                'use_confidence': False,
                'use_pool_pressure': False,
                'use_hazard': False
            },
            'C_distance_quantity': {
                **base_config,
                'use_urgency': False,
                'use_confidence': False,
                'use_pool_pressure': False,
                'use_hazard': False
            },
            'D_full_resqlink': base_config,
            'E_no_confidence': {**base_config, 'use_confidence': False},
            'F_no_pool_pressure': {**base_config, 'use_pool_pressure': False},
            'G_no_hazard': {**base_config, 'use_hazard': False},
            'H_full_rescan': {**base_config, 'strategy': 'full_rescan'},
        }

        if config_name not in configs:
            raise ValueError(f"Unknown ablation config: {config_name}. Available: {list(configs.keys())}")

        import copy
        return adapter.run(copy.deepcopy(requests), copy.deepcopy(resources), configs[config_name])

    @staticmethod
    def run_all_ablations(requests, resources):
        """Run all ablation configurations and return results dict."""
        configs = [
            'A_distance_only',
            'B_distance_urgency',
            'C_distance_quantity',
            'D_full_resqlink',
            'E_no_confidence',
            'F_no_pool_pressure',
            'G_no_hazard',
            'H_full_rescan'
        ]

        results = {}
        for config in configs:
            print(f"  Running ablation {config}...")
            results[config] = Ablations.run_ablation(requests, resources, config)

        return results

    @staticmethod
    def get_config_description(config_name: str) -> str:
        """Get human-readable description of ablation config."""
        descriptions = {
            'A_distance_only': 'Distance-only (nearest resource)',
            'B_distance_urgency': 'Distance + urgency weighting',
            'C_distance_quantity': 'Distance + quantity/partial allocation',
            'D_full_resqlink': 'Full ResQLink (incremental, all features)',
            'E_no_confidence': 'ResQLink without confidence scoring',
            'F_no_pool_pressure': 'ResQLink without pool pressure awareness',
            'G_no_hazard': 'ResQLink without hazard accessibility',
            'H_full_rescan': 'ResQLink with full re-scan (no incremental)',
        }
        return descriptions.get(config_name, config_name)