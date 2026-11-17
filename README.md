# CrossTalk on the Page

Open source research tools for studying language, evidence and visual design in *CrossTalk*, the defense software engineering journal.

The published 0.1.0 study examines 281 retained issue PDFs and 9,660 physical pages. It combines source indexing, native and OCR text extraction, corpus linguistics, statistical diagnostics and page-appearance analysis. The review register contains 2,708 complete AI-assisted article appraisals. Exact article counts cover 270 retained PDFs, with 11 open original print scopes. The historical issue and article totals are unresolved.

Read the [preprint and companion data on Zenodo](https://doi.org/10.5281/zenodo.24297224), inspect the [0.1.0 source](https://github.com/docxology/CrossTalk-study/tree/v0.1.0), or use [CITATION.cff](CITATION.cff) to cite the study.

## Install and test

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) to install the locked dependencies. The package requires Python 3.13 or newer, and `.python-version` records the verified Python 3.15.2 interpreter.

```sh
git clone https://github.com/docxology/CrossTalk-study.git
cd CrossTalk-study
uv sync --locked
uv run --locked crosstalk --help
uv run --locked pytest
```

The offline tests construct synthetic inputs. The repository supplies tools for inventory validation, bounded acquisition, extraction, indexing, search, linguistic measures and statistical diagnostics. Inspect a command's required inputs with `uv run --locked crosstalk COMMAND --help`. The `--root` option selects the research project directory used by a command.

The companion Zenodo deposit supplies derived measurements and source locators. Reanalyzing the historical corpus requires acquisition of the archival source documents and their provenance.

## Reproduce the preprint

The [versioned build kit](publication/CrossTalk-v0.1.0-preprint-build-inputs.zip) contains the authored manuscript, projection script, four graphical abstracts, ten analysis figures and their checksums.

For the published 0.1.0 render, use the linked 0.1.0 source tag. Extract the kit at the root of a clean checkout, then follow the extracted `BUILD.md`.

```sh
uv run --locked python -m zipfile -e publication/CrossTalk-v0.1.0-preprint-build-inputs.zip .
```

`BUILD.md` pins [docxology Template](https://github.com/docxology/template) at `f89cd527c7c688b9d67a995d584e026b2b5ccaab` and records the Pandoc, pandoc-crossref and XeLaTeX versions used for the verified render. Its Stage 03 command produces `output/pdf/Preprint_combined.pdf`. The included figures draw from original study measurements and coarse aggregate page maps.

The study edition is 0.1.0. The Python tooling has its own package version, 0.5.0.

## License and attribution

CrossTalk's original software, synthetic tests and software documentation are licensed under [Apache-2.0](LICENSE). The original manuscript, authored figures and derived study compilation are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

[LICENSE_SCOPE.md](LICENSE_SCOPE.md) identifies the material covered by each grant, the inherited Template notices and third-party source terms.

## Contributing

Use [GitHub issues](https://github.com/docxology/CrossTalk-study/issues) for reproducible bugs, documentation corrections and historical source leads. Include the command, source locator or figure involved and the evidence needed to reproduce the observation. Pull requests should preserve provenance, source distinctions and explicit coverage limits, and include relevant validation results.
