# SkillTransferBench catalog

[Project](../README.md) · [Benchmark guide](../benchmark/README.md)

35 task families · 408 executable cases · 6 domains.

## Systems

| Family | Cases | Main held-out | Lite held-out | Explore |
| --- | ---: | ---: | ---: | --- |
| [ACL inheritance](../benchmark/acl-permissions-inheritance/spec.yaml) | 13 | 6 | — | [Anchor](../benchmark/acl-permissions-inheritance/v01/) |
| [Database WAL recovery](../benchmark/db-wal-recovery/spec.yaml) | 11 | 7 | — | [Anchor](../benchmark/db-wal-recovery/v01/) |
| [Service decommissioning](../benchmark/decommissioning-service-with-sensitive-data/spec.yaml) | 6 | — | — | [Anchor](../benchmark/decommissioning-service-with-sensitive-data/v01/) |
| [Deterministic tarball](../benchmark/deterministic-tarball/spec.yaml) | 12 | 6 | — | [Anchor](../benchmark/deterministic-tarball/v01/) |
| [Git leak recovery](../benchmark/git-leak-recovery/spec.yaml) | 13 | 6 | 6 | [Anchor](../benchmark/git-leak-recovery/v01/) |
| [Password recovery](../benchmark/password-recovery/spec.yaml) | 5 | — | — | [Anchor](../benchmark/password-recovery/v01/) |
| [Obfuscated file recovery](../benchmark/recover-obfuscated-files/spec.yaml) | 7 | — | — | [Anchor](../benchmark/recover-obfuscated-files/v01/) |
| [Shell deobfuscation](../benchmark/shell-deobfuscation/spec.yaml) | 10 | — | — | [Anchor](../benchmark/shell-deobfuscation/v01/) |
| [SQLite recovery](../benchmark/sqlite-db-truncate/spec.yaml) | 14 | 6 | 6 | [Anchor](../benchmark/sqlite-db-truncate/v01/) |
| [Secret recovery](../benchmark/vulnerable-secret/spec.yaml) | 6 | — | — | [Anchor](../benchmark/vulnerable-secret/v01/) |

## Services

| Family | Cases | Main held-out | Lite held-out | Explore |
| --- | ---: | ---: | ---: | --- |
| [API scheduling](../benchmark/api-scheduler/spec.yaml) | 15 | 10 | — | [Anchor](../benchmark/api-scheduler/v01/) |
| [Flask service](../benchmark/flask/spec.yaml) | 9 | 6 | — | [Anchor](../benchmark/flask/v01/) |
| [Key-value store gRPC](../benchmark/kv-store-grpc/spec.yaml) | 16 | 6 | 6 | [Anchor](../benchmark/kv-store-grpc/v01/) |
| [PyPI server](../benchmark/pypi-server/spec.yaml) | 16 | 10 | 10 | [Anchor](../benchmark/pypi-server/v01/) |
| [WebAssembly pipeline](../benchmark/wasm-pipeline/spec.yaml) | 11 | — | — | [Anchor](../benchmark/wasm-pipeline/v01/) |

## Data Processing

| Family | Cases | Main held-out | Lite held-out | Explore |
| --- | ---: | ---: | ---: | --- |
| [Cocktail recipe extraction](../benchmark/cocktail-recipes/spec.yaml) | 8 | — | — | [Anchor](../benchmark/cocktail-recipes/v01/) |
| [HTML script filtering](../benchmark/filter-js-from-html/spec.yaml) | 16 | 10 | 10 | [Anchor](../benchmark/filter-js-from-html/v01/) |
| [JQ data processing](../benchmark/jq-data-processing/spec.yaml) | 12 | 7 | 7 | [Anchor](../benchmark/jq-data-processing/v01/) |
| [Multi-source data merging](../benchmark/multi-source-data-merger/spec.yaml) | 14 | — | — | [Anchor](../benchmark/multi-source-data-merger/v01/) |
| [Organization JSON](../benchmark/organization-json-generator/spec.yaml) | 13 | 8 | — | [Anchor](../benchmark/organization-json-generator/v01/) |
| [SPARQL queries](../benchmark/sparql-professors-universities/spec.yaml) | 15 | 10 | 10 | [Anchor](../benchmark/sparql-professors-universities/v01/) |

## Scientific Computing

| Family | Cases | Main held-out | Lite held-out | Explore |
| --- | ---: | ---: | ---: | --- |
| [Audio STFT peaks](../benchmark/audio-synth-stft-peaks/spec.yaml) | 11 | 10 | 10 | [Anchor](../benchmark/audio-synth-stft-peaks/v01/) |
| [Camera layout](../benchmark/camera-layout/spec.yaml) | 16 | — | — | [Anchor](../benchmark/camera-layout/v01/) |
| [Cross-entropy optimization](../benchmark/cross-entropy-method/spec.yaml) | 13 | 6 | — | [Anchor](../benchmark/cross-entropy-method/v01/) |
| [ODE solver RK4](../benchmark/ode-solver-rk4/spec.yaml) | 15 | 5 | — | [Anchor](../benchmark/ode-solver-rk4/v01/) |

## Finance

| Family | Cases | Main held-out | Lite held-out | Explore |
| --- | ---: | ---: | ---: | --- |
| [Bank transaction filtering](../benchmark/bank-trans-filter/spec.yaml) | 16 | 6 | — | [Anchor](../benchmark/bank-trans-filter/v01/) |
| [Financial analysis](../benchmark/financial-analysis/spec.yaml) | 7 | 6 | — | [Anchor](../benchmark/financial-analysis/v01/) |
| [Financial documents](../benchmark/financial-document-processor/spec.yaml) | 13 | 6 | — | [Anchor](../benchmark/financial-document-processor/v01/) |
| [HTML financial verification](../benchmark/html-finance-verify/spec.yaml) | 16 | 6 | 6 | [Anchor](../benchmark/html-finance-verify/v01/) |
| [Stock analysis](../benchmark/stock-analysis/spec.yaml) | 11 | — | — | [Anchor](../benchmark/stock-analysis/v01/) |

## Office Automation

| Family | Cases | Main held-out | Lite held-out | Explore |
| --- | ---: | ---: | ---: | --- |
| [Spreadsheet automation](../benchmark/excel-auto/spec.yaml) | 7 | — | — | [Anchor](../benchmark/excel-auto/v01/) |
| [Office workflows](../benchmark/office-workflow/spec.yaml) | 8 | 6 | — | [Anchor](../benchmark/office-workflow/v01/) |
| [Presentation editing](../benchmark/pptx-edit/spec.yaml) | 6 | — | — | [Anchor](../benchmark/pptx-edit/v01/) |
| [Spreadsheet formulas](../benchmark/xlsx-formula/spec.yaml) | 17 | — | — | [Anchor](../benchmark/xlsx-formula/v01/) |
| [Spreadsheet structure](../benchmark/xlsx-structure/spec.yaml) | 10 | 6 | 6 | [Anchor](../benchmark/xlsx-structure/v01/) |

Main and lite counts exclude anchors. Exact membership: [full](../configs/scopes/full.yaml), [main](../configs/scopes/main.yaml), [lite](../configs/scopes/lite.yaml).
