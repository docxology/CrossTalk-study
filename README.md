# CrossTalk research tooling

This code supports provenance-aware linguistic and visual analysis of CrossTalk. It includes acquisition policy checks, issue and article indexing, PDF processing, and methods for analyzing text and page appearance.

The included offline tests construct their own inputs. The historical study uses separately held source documents, source observations, and generated outputs. This checkout provides the code and synthetic tests needed to inspect the methods.

Use Python 3.13 or newer. Run `crosstalk --help` with the package installed to inspect the entry point. Run `pytest` with the declared development dependencies to exercise the included fixtures.

The version DOI for the edition 0.1.0 preprint is [10.5281/zenodo.24297224](https://doi.org/10.5281/zenodo.24297224).

See the [license scope](LICENSE_SCOPE.md) for inherited terms and the release terms for original contributions.

## Preprint build

The [versioned build kit](publication/CrossTalk-v0.1.0-preprint-build-inputs.zip) supplies authored manuscript inputs,
the Template projection entry point and checksum-bound figures. The files
do not contain journal scans or raw extracted text. The page-shape figure
draws four pooled darkness maps as coarse vector grids. Extract the kit into a copy of this
checkout and follow its `BUILD.md`. The code and kit reproduce the preprint
render. Reanalysis of the full corpus requires the separately sourced archival
holdings and acquisition provenance. Read the paper's coverage and limitations
before using the supplied artifact for historical inference.

The [tagged source for 0.1.0](https://github.com/docxology/CrossTalk-study/tree/v0.1.0) corresponds to the Zenodo record above. The Python tooling retains its independent package version, 0.5.0.
