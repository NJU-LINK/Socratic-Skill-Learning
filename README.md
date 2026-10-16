<p align="center">
  <img src="docs/assets/nju-link-logo.png" width="84" alt="NJU-LINK" />
</p>

<h1 align="center">Socratic Skill Learning</h1>

<p align="center"><strong>Interleaving Teaching and Practice for Transferable Agent Skills</strong></p>

<p align="center"><strong>NJU-LINK</strong> · Nanjing University</p>

<p align="center">
  <a href="https://arxiv.org/abs/2610.17860"><img src="https://img.shields.io/badge/arXiv-2610.17860-a04b4b.svg?logo=arxiv&amp;logoColor=white" alt="Paper on arXiv" /></a>
  <a href="https://huggingface.co/datasets/NJU-LINK/SkillTransferBench"><img src="https://img.shields.io/badge/Hugging_Face-SkillTransferBench-967348.svg?logo=huggingface&amp;logoColor=white" alt="SkillTransferBench on Hugging Face" /></a>
  <a href="docs/README.md"><img src="https://img.shields.io/badge/Docs-Guide-64737d.svg?logo=readthedocs&amp;logoColor=white" alt="Documentation" /></a>
</p>

## Overview

**Socratic Skill Learning (SSL)** develops reusable agent Skills by interleaving
a Student's practice with an Educator's guidance. The Student authors the
package, which fresh solvers apply to unseen tasks.

Fixed-Window SSL reviews progress at regular intervals. Issue-Guided SSL
focuses review on unresolved learning issues as they change.

<p align="center">
  <picture><source media="(max-width: 640px)" srcset="docs/assets/repo-overview-mobile.svg"><img src="docs/assets/repo-overview.svg" width="880" alt="The Educator guides Student practice. The Student tests and authors a Skill package, which fresh solvers apply to unseen tasks."></picture>
</p>

<details>
<summary>Full method diagram</summary>

![SSL method and review policies](docs/assets/method-overview.png)

</details>

## SkillTransferBench

**35 task families · 408 executable cases · 6 domains.**
Public family specifications define what can vary; fresh solver sessions test
whether learned Skills transfer to held-out cases.

<p align="center">
  <picture><source media="(max-width: 640px)" srcset="docs/assets/benchmark-atlas-mobile.svg"><img src="docs/assets/benchmark-atlas.svg" width="880" alt="Six domains of executable tasks, with representative workflows and family / case counts."></picture>
</p>

The main evaluation uses **22 families / 155 held-out cases**; cross-model
experiments use a shared **10-family / 77-case** subset.
Browse specifications and download executable tasks on
[Hugging Face](https://huggingface.co/datasets/NJU-LINK/SkillTransferBench).

## Results

<p align="center">
  <picture><source media="(max-width: 640px)" srcset="docs/assets/results-summary-mobile.svg"><img src="docs/assets/results-summary.svg" width="880" alt="Fixed-Window SSL utility gains over No Skill: Qwen main +7.8 pp, DeepSeek shared +3.1 pp, Kimi shared +8.2 pp. Issue-Guided SSL saves 61.7%, 63.8%, 77.4% Educator tokens against Fixed-Window SSL."></picture>
</p>

[Full comparisons and model settings](docs/results.md).

## Quick Start

Requires **Node.js 22.19+**, **Docker**, and an OpenAI-compatible model endpoint.

```bash
git clone https://github.com/NJU-LINK/Socratic-Skill-Learning.git
cd Socratic-Skill-Learning
npm ci
cp .env.example .env
```

Set `SSL_URL` and `SSL_KEY` in `.env` and start Docker.

Learn and evaluate a Skill on one task family:

```bash
npm run ssl -- run --scope main --model qwen \
  --methods issue-guided-ssl --families html-finance-verify \
  --replicates 1
```

Add `--dry-run` to preview the plan without model calls.

The [documentation](docs/README.md) covers setup, released Skills, and offline analysis.

## Citation

<details>
<summary><b>BibTeX</b></summary>

```bibtex
@misc{zhu2026socraticskilllearning,
  title  = {Socratic Skill Learning: Interleaving Teaching and Practice
            for Transferable Agent Skills},
  author = {Letian Zhu and Han Li and Yifan Yao and Xinping Lei
            and Xinyu Che and Jiahao Wang and Dianyi Wang and Yucheng Fu
            and Jiakai Wang and Zhiqi Bai and Wenbo Su and Jiaheng Liu},
  year   = {2026},
  eprint = {2610.17860},
  archivePrefix = {arXiv},
  primaryClass = {cs.AI},
  doi    = {10.48550/arXiv.2610.17860},
  url    = {https://arxiv.org/abs/2610.17860}
}
```

</details>

## License

Original code is [MIT licensed](LICENSE). Benchmark materials retain their
[source-specific licenses and attribution](THIRD_PARTY_NOTICES.md).

<details>
<summary>Acknowledgments</summary>

Runtime: [Pi](https://github.com/earendil-works/pi) · Baseline adapters:
[Trace2Skill](https://github.com/Qwen-Applications/Trace2Skill) and
[SKILL-KD](https://github.com/KhanCold/SKILL-KD).

</details>
