# Phase 7: Evaluation Framework

This framework tests the ResQLink matching engine against conventional baseline approaches to prove measurable performance and correctness improvements, fulfilling the DBTHON novelty requirements.

## Current State
**Framework: COMPLETE.** 
**Mock Evaluation: COMPLETE.** 
**Real-Engine Evaluation: PENDING.** 
Since Phase 4 (Matching Engine) and Phase 2b (DB internals) are currently pending integration, this framework uses a mock adapter (`adapter.py`) to simulate database responses, latency, and rows scanned. No evaluation logic needs to be rewritten when the real DB is ready.

## Components
- `adapter.py`: A clean interface abstracting the matching engine. Contains `MockAdapter` and `RealResQLinkAdapter`.
- `baselines.py`: Conventional distance-only, urgency-distance, and full-rescan execution blocks.
- `ablations.py`: Configurations mapping to the Phase 7 A-H ablation table.
- `metrics.py`: Calculation of coverage, latency p95, double allocations, and rows evaluated.
- `runner.py`: The main execution script.
- `charts.py`: Generates visualization plots in `/charts`.
- `report_generator.py`: Generates the DBTHON-ready `evaluation-report.md`.
- `scalability.py` & `concurrency.py`: Harnesses to test scale (10k, 100k, 1M) and concurrency (0 double-allocation rule).

## Usage
1. `python runner.py`
2. `python charts.py`
3. `python report_generator.py`
4. `python scalability.py`
