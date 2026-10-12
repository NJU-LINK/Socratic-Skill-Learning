# Experiment records

Start with a run's `meta.json` for its scores and session inventory, and
`skill/` for the resulting reusable package. These files are directly
browsable. Full JSONL session logs are compressed by experiment group;
two representative SSL runs also remain available without unpacking.
`r1`, `r2`, and `r3` denote independent runs; `iteration-N` denotes a checkpoint
within a run.

## Experiments

| Directory | Experiment | Families | Methods / conditions | Runs per condition | Release coverage |
| --- | --- | ---: | ---: | ---: | --- |
| [Main · Qwen](main/qwen/) | Main comparison | 22 | 7 methods | 3 | Skill formation, training, held-out sessions and scores, Skill packages |
| [Cross-model · DeepSeek](cross-model/deepseek/) | Cross-model comparison | 10 | 5 methods | 1 | Skill formation and packages; No-Skill held-out sessions |
| [Cross-model · Kimi](cross-model/kimi/) | Cross-model comparison | 10 | 5 methods | 1 | Skill formation and packages; No-Skill held-out sessions |
| [Review intervals](review-intervals/) | Fixed-Window SSL review interval | 22 | g = 5, 20 | 3 | Skill formation, packages, held-out scores, and aggregate results |

The main cohort contains 155 held-out cases and the cross-model subset contains
77. Their exact task lists are in [main.yaml](../configs/scopes/main.yaml)
and [lite.yaml](../configs/scopes/lite.yaml). Model pairs are specified in
[qwen.yaml](../configs/models/qwen.yaml),
[deepseek.yaml](../configs/models/deepseek.yaml), and
[kimi.yaml](../configs/models/kimi.yaml).

Cross-model performance is reported in the paper. Here the Skill methods
provide learning records and packages, and the `no-skill` directories provide
held-out solving sessions.

## Follow one run

For `html-finance-verify`, compare the same family and run under the two SSL
review policies:

| Read | Fixed-Window SSL | Issue-Guided SSL |
| --- | --- | --- |
| Session inventory and scores | [meta.json](main/qwen/fixed-window-ssl/r1/html-finance-verify/meta.json) | [meta.json](main/qwen/issue-guided-ssl/r1/html-finance-verify/meta.json) |
| Student practice and revisions | [student-author.jsonl](main/qwen/fixed-window-ssl/r1/html-finance-verify/skill-formation/student-author.jsonl) | [student-author.jsonl](main/qwen/issue-guided-ssl/r1/html-finance-verify/skill-formation/student-author.jsonl) |
| Educator reviews | [max-educator.jsonl](main/qwen/fixed-window-ssl/r1/html-finance-verify/skill-formation/max-educator.jsonl) | [max-educator.jsonl](main/qwen/issue-guided-ssl/r1/html-finance-verify/skill-formation/max-educator.jsonl) |
| Final Skill package | [iteration-3](main/qwen/fixed-window-ssl/r1/html-finance-verify/skill/iteration-3/) | [iteration-3](main/qwen/issue-guided-ssl/r1/html-finance-verify/skill/iteration-3/) |
| One held-out solving session | [v05.jsonl](main/qwen/fixed-window-ssl/r1/html-finance-verify/heldout/v05.jsonl) | [v05.jsonl](main/qwen/issue-guided-ssl/r1/html-finance-verify/heldout/v05.jsonl) |

The corresponding task is [benchmark/html-finance-verify/v05](../benchmark/html-finance-verify/v05/).
Both example runs retain all their session logs. The other runs follow the
same layouts after unpacking their group.

## Read the full session logs

[Session archives](archives/) contain the full JSONL logs grouped by experiment.
From the repository root, list the available groups or restore one group:

```bash
python3 scripts/unpack-experiments.py --list
python3 scripts/unpack-experiments.py --group main-qwen
```

| Group | Sessions restored under |
| --- | --- |
| `main-qwen` | `experiments/main/qwen/` |
| `cross-model-deepseek` | `experiments/cross-model/deepseek/` |
| `cross-model-kimi` | `experiments/cross-model/kimi/` |
| `review-g5` | `experiments/review-intervals/g5/` |
| `review-g20` | `experiments/review-intervals/g20/` |

The tool reads [archives/manifest.json](archives/manifest.json) and restores
the original file paths. To restore every group's logs:

```bash
python3 scripts/unpack-experiments.py --all
```

Scores, CSV tables, and frozen Skills stay outside the archives. Neither
[offline score summaries](../docs/running.md#recompute-the-main-results-offline)
nor [frozen-Skill evaluation](../docs/running.md#evaluate-a-released-skill)
requires unpacking.

## Directory layouts

```text
main/qwen/<method>/r<N>/<family>/
cross-model/deepseek/r1/<method>/<family>/
cross-model/kimi/r1/<method>/<family>/
review-intervals/<g5|g20>/r<N>/<family>/
```

Method directories use the [paper names](../docs/running.md#method-names):
`expert-authoring`, `post-hoc-teaching`, `fixed-window-ssl`, `issue-guided-ssl`,
`no-skill`, `trace2skill`, and `skill-kd`. The cross-model cohorts contain the
first five. Each run's `meta.json` uses the same method identifier.

| File or directory | Contents |
| --- | --- |
| `meta.json` | Method, family, run number, session counts, and available scores |
| `skill-formation/*.jsonl` | Sessions that produce and revise the Skill; separate Student and Educator files for SSL |
| `train/iteration-*.jsonl` | Training-iteration solving sessions |
| `heldout/v*.jsonl` | Available held-out solving sessions; the final attempt is retained after retries |
| `skill/` | `SKILL.md` and bundled resources; Qwen packages are organized by `iteration-N/` |

Use the highest numbered Skill iteration for the final Qwen package. Directory
availability depends on the method: No-Skill has no acquisition or Skill package.
Each `meta.json` records the released session inventory; most JSONL files
are supplied in the corresponding archive.

Each JSONL line is one message record with `i` and `role` (`user`, `assistant`,
or `toolResult`), plus applicable fields such as `text`, `thinking`, `toolCalls`,
`toolCallId`, `toolName`, and `isError`.

## Scores

- **Main comparison:** per-case scores are in each Qwen run's
  `meta.json` under `stats.heldout`. Average cases within each family, then
  families equally, then the three runs to obtain the reported utility.
- **Review intervals:** [summary.json](review-intervals/summary.json) provides
  aggregates on the 155-case main cohort. Per-case scores are in run-level
  `meta.json` under `heldout`; [results/](review-intervals/results/) retains
  the raw score tables. The g = 10 reference is `main/qwen/fixed-window-ssl/`.

See the [evaluation guide](../docs/running.md) to evaluate a released Skill package.
