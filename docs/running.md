# Running Socratic Skill Learning

Use this harness to evaluate a released Skill or learn a new one on
SkillTransferBench. Method names in commands and directories match the
[method names](#method-names). The examples below start with **one family,
one replicate, and one method**: Issue-Guided SSL on `html-finance-verify`,
run 1. Run commands from the repository root unless stated otherwise.

## Read the released records

Scores and frozen Skills can be browsed without installing the harness or
unpacking archives. Each run's `meta.json` lists its sessions and available
scores; `skill/` contains the reusable package. For example, inspect the main comparison's
[Issue-Guided SSL run](../experiments/main/qwen/issue-guided-ssl/r1/html-finance-verify/)
and its [final Skill](../experiments/main/qwen/issue-guided-ssl/r1/html-finance-verify/skill/iteration-3/).
The two representative SSL runs retain their complete JSONL logs. To read
other runs' dialogue, [unpack the corresponding experiment group](../experiments/README.md#read-the-full-session-logs).

## Recompute the main results offline

With Node.js >= 20, summarize the released Qwen main comparison:

```bash
node scripts/summarize-main.mjs
node scripts/summarize-main.mjs --out out/main-summary.csv
```

This script needs no npm dependencies, API credentials, or Docker. It reads
`meta.json` for all seven methods, checks that all three replicates cover the
same 22 families and 155 held-out cases, and prints each replicate's utility
and Avg@3. Use `--records <dir>` to read another copy of `experiments/main/qwen`.
Session archives are not needed.

Utility is the mean case score within each family, averaged equally across
families. Avg@3 averages those utilities across the three independent runs;
it does not select the best run. A recorded score is included even when its
session transcript is unavailable. The CSV summarizes the published main
utility scores; acquisition costs and the other experiments are documented
in the paper and [experiment guide](../experiments/README.md).

## Set up the harness

Running acquisition or evaluation requires Node.js >= 22.19.0, a running Docker
daemon, and an OpenAI-compatible model endpoint. The external baselines also
require Python 3 and Git.

Task images must include Bash and GNU `timeout` (from coreutils), so shell
and verifier deadlines are enforced inside the container. The provided
Ubuntu/Debian-based benchmark images meet this requirement.

The dependency-free offline summary above also works with Node.js 20.

```bash
npm ci
npm run check
npm test
cp .env.example .env
```

Pi remains pinned to 0.81.1. The project lockfile and scoped overrides use
patched versions of `undici`, `brace-expansion`, and `protobufjs` instead of
Pi's upstream shrinkwrap versions. Keep the project lockfile when updating
dependencies; `npm test` checks the versions actually loaded by Pi.

Fill `SSL_URL` and `SSL_KEY` in `.env`, or set them in your environment.
The model pair and token limits come from the selected model YAML. If Docker
builds need a proxy, set `DOCKER_PROXY` to a URL reachable from Docker.

## Evaluate a released Skill

Inspect the plan, then evaluate the shipped Qwen package. Its frozen Skill
is already available; no session archive needs to be unpacked:

```bash
npm run ssl -- evaluate --scope main --model qwen \
  --methods issue-guided-ssl --families html-finance-verify --replicates 1 \
  --frozen experiments/main/qwen --dry-run

npm run ssl -- evaluate --scope main --model qwen \
  --methods issue-guided-ssl --families html-finance-verify --replicates 1 \
  --frozen experiments/main/qwen
```

This uses the final `iteration-3` package and fresh Student sessions for the
family's six held-out cases. Results are written under
`out/runs/frozen-eval/issue-guided-ssl/r1/html-finance-verify/`.

For a cross-model package, pair its cohort with the corresponding model and
`lite` scope. For example:

```bash
npm run ssl -- evaluate --scope lite --model deepseek \
  --methods fixed-window-ssl --families html-finance-verify --replicates 1 \
  --frozen experiments/cross-model/deepseek
```

## Learn and evaluate a new Skill

Inspect the acquisition plan before starting a new run:

```bash
npm run ssl -- run --scope main --model qwen \
  --methods issue-guided-ssl --families html-finance-verify --replicates 1 \
  --dry-run

npm run ssl -- run --scope main --model qwen \
  --methods issue-guided-ssl --families html-finance-verify --replicates 1
```

`run` learns a Skill over three iterations and evaluates the final frozen
package on the family's held-out cases. Results, raw sessions, and Skill
snapshots are stored in `out/runs/`.

The stages can also run separately. Replace `run` with `acquire` to learn
without held-out evaluation. Then use `evaluate` with the same scope, model,
method, family, and replicate; `--runs <dir>` selects an alternative raw-run
root. Record export is an [optional postprocessing step](#export-records-for-inspection).

## Select tasks, models, and methods

Scopes and model configurations are independent. Use a built-in name or a
path to a YAML file:

| Scope | Families | Held-out cases | Independent runs |
| --- | ---: | ---: | ---: |
| [main](../configs/scopes/main.yaml) | 22 | 155 | 3 |
| [lite](../configs/scopes/lite.yaml) | 10 | 77 | 1 |
| [full](../configs/scopes/full.yaml) | 35 | 373 | 1 |

The full catalog has 408 task variants, including 35 `v01` anchors used for
learning. `full` evaluates the other 373 variants. The scope files also set
iteration counts and output roots; copy
[custom.example.yaml](../configs/scopes/custom.example.yaml) to define a smaller
or different task selection.

Model configurations are [qwen](../configs/models/qwen.yaml),
[deepseek](../configs/models/deepseek.yaml), and [kimi](../configs/models/kimi.yaml).
For another endpoint or model pair, copy
[the custom model example](../configs/models/custom.example.yaml) and pass its
path with `--model`.

- `--families a,b` and `--replicates 1,2` select a subset of the scope.
- `--methods` selects any subset of
  `expert-authoring,post-hoc-teaching,fixed-window-ssl,issue-guided-ssl,no-skill`.
  Omitting it selects all five methods. No Skill has no package to freeze;
  run it through `acquire --methods no-skill` or `run --methods no-skill`.
- `--frozen <dir>` evaluates packages from a released experiment cohort.
- `--bench <dir>` overrides the benchmark root, which defaults to `./benchmark`.
- `--dry-run` prints a plan without model calls for `run`, `acquire`, or `evaluate`.

See `npm run ssl -- --help` for the complete command reference.

### Method names

| Paper name | Command / record identifier |
| :--- | :--- |
| Fixed-Window SSL | `fixed-window-ssl` |
| Issue-Guided SSL | `issue-guided-ssl` |
| Expert Authoring | `expert-authoring` |
| Post-hoc Teaching | `post-hoc-teaching` |
| No Skill | `no-skill` |
| Trace2Skill | `trace2skill` |
| SKILL-KD | `skill-kd` |

Native methods share the `ssl` CLI. Trace2Skill and SKILL-KD use their own
[baseline entry points](#run-the-external-baselines).

## Run the external baselines

Trace2Skill and SKILL-KD use their own commands and pinned upstream revisions.
Their baseline YAMLs select the workload and models; the native methods'
`--scope` and `--model` flags do not apply to these commands.

```bash
npm run ssl -- trace2skill setup
npm run ssl -- trace2skill validate
npm run ssl -- trace2skill run --family html-finance-verify --replicate 1 --phase all

npm run ssl -- skill-kd setup
npm run ssl -- skill-kd plan
npm run ssl -- skill-kd run --family html-finance-verify --replicate 1 --phase all
```

Setup installs the upstream code and Python dependencies. Validation and
planning do not call a model. After setup, add `--dry-run` to either `run`
command to inspect its plan. Use `npm run ssl -- trace2skill --help` or
`npm run ssl -- skill-kd --help` for options, including `--config`.

The default configurations are
[trace2skill-baseline.yaml](../configs/trace2skill-baseline.yaml) and
[skill-kd-baseline.yaml](../configs/skill-kd-baseline.yaml). These files record
the upstream revision, task scope, model pair, and acquisition settings used
by each adaptation.

## Find the implementation and output

- [cli.ts](../src/cli.ts) and [runner.ts](../src/runner.ts) provide the command entry
  and acquisition/evaluation stages; [methods.ts](../src/methods.ts) maps public
  names to runtime modes.
- [orchestrator.ts](../src/experiment/orchestrator.ts) runs learning iterations,
  freezes complete Skill packages, and starts fresh evaluation sessions.
- [education.ts](../src/agent/education.ts) handles Educator review and dialogue;
  [learning-issue-tree.ts](../src/agent/learning-issue-tree.ts) manages the persistent
  issues used by Issue-Guided SSL; [prompts.ts](../src/agent/prompts.ts) defines the
  role prompts.
- `src/runtime/` provides Docker execution and scoring; `src/baselines/`
  contains the external-method adaptations.

## Export records for inspection

Learning and evaluation write their results directly to `out/runs/`.
If you want a compact JSONL view of completed native-method sessions and
copies of their Skill packages, run this optional tool:

```bash
node --import tsx scripts/export-records.ts --runs out/runs --out out/records
```

The output layout is:

```text
out/records/<method>/r<N>/<family>/{meta.json, skill-formation/, train/, heldout/, skill/}
```

Each JSONL line is one message record, with applicable fields such as `i`,
`role`, `text`, `thinking`, `toolCalls`, `toolCallId`, `toolName`, and `isError`.
Export normalizes host workspace paths to `/run`. For file availability and
how to follow a Student–Educator interaction, see the
[experiment guide](../experiments/README.md).
