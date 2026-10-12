# Licenses and sources

The [MIT license](LICENSE) covers the original SSL harness, configuration,
scripts, tests, and accompanying code documentation. It does not relicense
the benchmark, experimental records and Skill packages, third-party files,
or laboratory artwork. Existing notices in individual files remain applicable.

## Benchmark sources

SkillTransferBench adapts tasks and constructs new variants using the source
benchmarks below. This is a source list for the collection, not a claim that
every family derives from every source. Specifications and preparation
records are under [benchmark/](benchmark/README.md).

| Source | Upstream terms |
| --- | --- |
| [Terminal-Bench](https://github.com/harbor-framework/terminal-bench-1) | Apache-2.0: [included license](licenses/Apache-2.0.txt), [upstream license](https://github.com/harbor-framework/terminal-bench-1/blob/main/LICENSE) |
| [AgentIF-OneDay](https://github.com/xbench-ai/AgentIF-OneDay) | [Official Hugging Face dataset card](https://huggingface.co/datasets/xbench/AgentIF-OneDay): MIT for the published dataset; no license covering the entire GitHub repository was identified in its root files |
| [SpreadsheetBench](https://github.com/RUCKBReasoning/SpreadsheetBench) | [README license section](https://github.com/RUCKBReasoning/SpreadsheetBench#license-and-citation): CC BY-SA 4.0 |
| [CodeContests](https://github.com/google-deepmind/code_contests) | [README license section](https://github.com/google-deepmind/code_contests#license) distinguishes code and non-code materials |
| [FullStackBench](https://github.com/bytedance/FullStackBench) | [Upstream README](https://github.com/bytedance/FullStackBench): [Apache-2.0](licenses/Apache-2.0.txt) for code and CC BY-SA 4.0 for data |
| [OfficeBench](https://github.com/zlwang-cs/OfficeBench) | Apache-2.0: [included license](licenses/Apache-2.0.txt), [upstream license](https://github.com/zlwang-cs/OfficeBench/blob/main/LICENSE) |

Upstream declarations were checked on 2026-10-09; the AgentIF-OneDay dataset
card was additionally verified on 2026-10-12. Their licenses apply to
the corresponding source material. The root MIT license does not grant a
blanket license over the derived benchmark or its fixtures. The terms for
individual task inputs and supporting files remain with their sources;
an additional collection-wide benchmark license has not been assigned here.

Source material and adaptations governed by
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/legalcode.en)
remain under that license. Original task-author credits, pinned source links,
and workbook modification notices are retained in
[benchmark attribution](benchmark/ATTRIBUTION.md). The 24 verified
Terminal-Bench anchor specifications also carry source and adaptation comments.

## Runtime and comparison methods

- [Pi](https://github.com/earendil-works/pi) supplies the agent runtime
  ([MIT](https://github.com/earendil-works/pi/blob/main/LICENSE)). Other npm
  dependencies retain the licenses distributed with their packages.
- [Trace2Skill](https://github.com/Qwen-Applications/Trace2Skill) declares
  [Apache-2.0](licenses/Apache-2.0.txt) in its README. The adapter uses the upstream version recorded
  in `configs/`; upstream artifacts retain their own notices.
- [SKILL-KD](https://github.com/KhanCold/SKILL-KD) is obtained separately by
  the baseline setup. Its upstream code is not included in this repository
  or relicensed by SSL.

## Experiment records and artwork

The records and model-generated Skill packages in `experiments/` are research
artifacts supplied with the study. The root code license does not assign
them a separate dataset license or supersede terms of their task inputs.

The NJU-LINK laboratory logo comes from the official
[laboratory template](https://github.com/NJU-LINK/latex-template). The logo
wordmark's [font license](docs/assets/logo-font-OFL.txt) is retained separately;
it does not grant rights to the laboratory name or logo. See the
[asset guide](docs/assets/README.md) for figure provenance.
