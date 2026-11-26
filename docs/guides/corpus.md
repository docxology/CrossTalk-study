# Corpus research workflow

Use a separate research directory to retain source captures, reviewed inventories and generated receipts. The companion deposit provides derived measurements and locators. Recalculating from the historical corpus requires the archival PDFs and source provenance. [Companion data](https://doi.org/10.5281/zenodo.24297224)

Each example assumes the package is installed in the active checkout and `research` is your existing research directory.

| Task | Command after `uv run --locked crosstalk` | Inputs and outputs |
| --- | --- | --- |
| Normalize a rendered-series catalog capture | `import-catalog CAPTURE --root research` | Writes `data/manifest/catalog.jsonl` and a catalog report. Preserves observed date conflicts. |
| Check a reviewed issue inventory | `validate --root research` | Reads `data/manifest/issues.jsonl` and reports the validated record count. |
| Resolve publisher locators | `resolve --root research` | Uses catalog records and published Signposting to check permitted PDF locators. |
| Acquire issue PDFs | `download --root research --limit 5` | Attempts a bounded set of reviewed URLs and retains verified PDFs and their acquisition evidence. |
| Extract page evidence | `extract --root research --max-pages 200` | Reads local PDFs and writes source-bound records in `data/processed/pages/`. |
| Build the current index | `index --root research` | Rebuilds catalog and page indexes in `data/processed/index/` and writes `output/reports/corpus-index.html`. |
| Retrieve indexed pages | `search "software process" --root research` | Finds pages matching all supplied literal terms and returns bounded excerpts. |
| Produce exploratory measures | `analyze --root research` | Writes the analysis report to `output/reports/analysis.html`. |
| Measure vocabulary and repetition | `linguistics --root research` | Writes the linguistic report to `output/reports/linguistics.html`. |
| Compute issue-level diagnostics | `statistics --root research` | Writes issue and page tables, resampling diagnostics, figures and `output/reports/statistics.html`. |

`import-publisher CAPTURE --root research` ingests official publisher cards. Use the `publisher download`, `publisher extract` and `publisher index` subcommands for the separate publisher dataset under `data/publisher/`. Use `uv run --locked crosstalk publisher --help` to list its subcommands. Both acquisition paths respect host policy and bounded request intervals.

Keep the PDF checksum, physical page index and admitted text layer together when interpreting results. Physical page coverage, exact article counts for attested issue scopes and complete appraisals of distinct works have different denominators. Review the [study methods](../manuscript/02_methods.md) and [source and evidence units](../manuscript/90_appendix_inventory.md) before comparing coverage.

[Documentation index](../README.md)
