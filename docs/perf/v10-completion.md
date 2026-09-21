# V10 performance gate

Release candidate: HomeIntent 5.0.2 / V10 Hardening. Measurement date: 2026-09-20.

Command:

```bash
python scripts/benchmark_v10.py \
  --registry-size 5000 \
  --iterations 30 \
  --max-p95-ms 100
```

Observed on the release workspace:

| Scenario | p95 |
|---|---:|
| simple goal understanding | 16.511 ms |
| routine plan (5k registry) | 45.820 ms |
| ten-step plan (5k registry) | 17.811 ms |
| presence monitor dispatch | 0.001 ms |
| dynamic open-window query (5k registry) | 10.211 ms |
| notification-target lookup | 0.001 ms |
| effect-state lookup | 0.001 ms |
| failure-explanation lookup | 0.021 ms |

All measured V10 microbenchmarks were below the 100 ms p95 gate. The CI runs
the same script. These values describe the deterministic, hass-free goal and
planning core; Home Assistant service latency and device response time are
external and intentionally excluded.

The workspace had a system load of roughly 55 on four visible CPUs during
this run. The V10 gate still passed and remains unchanged at 100 ms. The
separate V9 local run was load-distorted and is not claimed as a green gate;
the release report uses the clean CI runner's unchanged V9 gate values.
