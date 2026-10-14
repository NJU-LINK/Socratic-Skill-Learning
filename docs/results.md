# Results

[← Project overview](../README.md#results) · [Paper](https://arxiv.org/abs/2610.17860)

## Main comparison

Qwen3.7-Plus → Qwen3.7-Max · 22 families / 155 held-out cases · 3 runs.

| Method | Utility |
| --- | ---: |
| No Skill | 0.723 |
| Expert Authoring | 0.728 |
| Post-hoc Teaching | 0.748 |
| Trace2Skill | 0.761 |
| SKILL-KD | 0.751 |
| Fixed-Window SSL | **0.801** |
| Issue-Guided SSL | **0.805** |

## Shared-subset comparison

10 families / 77 held-out cases. Qwen: 3 runs; DeepSeek and Kimi: 1 run.

| Method | Qwen | DeepSeek | Kimi |
| --- | ---: | ---: | ---: |
| No Skill | 0.717 | 0.754 | 0.679 |
| Expert Authoring | 0.728 | 0.766 | 0.738 |
| Post-hoc Teaching | 0.710 | 0.759 | 0.721 |
| Fixed-Window SSL | 0.758 | **0.784** | **0.762** |
| Issue-Guided SSL | **0.762** | 0.779 | 0.753 |

## Model pairs

Student → Educator:

- [Qwen3.7-Plus → Qwen3.7-Max](../configs/models/qwen.yaml)
- [DeepSeek-V4-Flash-0731 → DeepSeek-V4-Pro-0813](../configs/models/deepseek.yaml)
- [Kimi K2.5 → Kimi K3](../configs/models/kimi.yaml)

## Metrics and sources

Utility averages case scores within each family, then equally across families
and independent runs. Trace2Skill and SKILL-KD are adapted baselines.

Educator-token savings compare Issue-Guided SSL with Fixed-Window SSL:

| Model pair | Subset | Educator tokens saved |
| --- | --- | ---: |
| Qwen | Main · 22 families / 155 cases | 61.7% |
| DeepSeek | Shared · 10 families / 77 cases | 63.8% |
| Kimi | Shared · 10 families / 77 cases | 77.4% |

[Recompute Qwen utilities](running.md#recompute-the-main-results-offline) ·
[Result sources](assets/results-data.json) · [Main results figure](assets/results-overview.png)

