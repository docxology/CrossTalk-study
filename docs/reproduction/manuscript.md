# Render the study manuscript

The maintained [manuscript](../manuscript/README.md) contains the ordered sections, configuration, preamble and bibliography. The [edition manifest](template-render-inputs-v0.1.0.csv) binds the published inventory, four graphical abstracts, ten body figures, derived inputs and prepared display values to the study edition.

Start in a clean `CrossTalk-study` checkout. Install uv, Pandoc 3.14, pandoc-crossref 0.3.26 built with Pandoc 3.14, and XeLaTeX with the packages listed by Template's render preflight. The commands below use the Template revision tested for this checkout. [Template prerequisites](https://github.com/docxology/template/blob/87704feae0a4490ef7dad9c931d268e8c30273c2/docs/RUN_GUIDE.md)

```sh
study="$(pwd -P)"
git clone https://github.com/docxology/template.git ../CrossTalk-template
git -C ../CrossTalk-template checkout --detach 87704feae0a4490ef7dad9c931d268e8c30273c2
uv run --locked python scripts/z_generate_manuscript_variables.py --release

cd ../CrossTalk-template
uv sync --locked --no-dev
mkdir -p projects/working
ln -s "$study" projects/working/CrossTalk-study
SOURCE_DATE_EPOCH=1794873600 uv run --no-sync python scripts/pipeline/stage_03_render.py \
  --project working/CrossTalk-study --skip-manuscript-hydration
uv run --no-sync python scripts/pipeline/stage_04_validate.py \
  --project working/CrossTalk-study
```

The hydration step checks the build kit and manifest hashes, then extracts the exact manifest-listed data and figures into `output/`. It writes resolved sections and configuration to `output/manuscript/`. The bundle carries study-authored figures and coarse aggregate page maps. The render consumes these inputs without acquiring journal scans.

Open `output/pdf/CrossTalk-study_combined.pdf` in the study checkout. Check the cover, four graphical abstracts, methods, results, discussion, ten body figures, appendix and resolved bibliography. Stage 04 writes validation and provenance reports in `output/reports/`. Hydration writes a separate receipt under `output/reports/template-projection/`.

The [claim ledger](../manuscript/claim_ledger.yaml) records the source for selected reported figures. It links archived historical observations to their positions in the published 0.1.0 study and display statistics to their retained data or figures. The published PDF has SHA-256 `286a6b3a13d333145cc78148886182d850f1112b1771df85ef985b902ed0bcef`. [Published PDF](https://zenodo.org/records/24297224/files/CrossTalk-on-the-Page-v0.1.0.pdf#page=10)

For independently reviewed study inputs, put the declared data and figures in their manifest paths and set `CROSSTALK_TEMPLATE_MANIFEST` to the manifest's absolute path and `CROSSTALK_TEMPLATE_MANIFEST_SHA256` to its independently verified digest. Run the hydration command without `--release`, then use the same render and validation steps.

The 0.1.0 [build kit](../../publication/CrossTalk-v0.1.0-preprint-build-inputs.zip) and [versioned source snapshot](https://github.com/docxology/CrossTalk-study/tree/v0.1.0) record the inputs for the published PDF. The [Zenodo version record](https://doi.org/10.5281/zenodo.24297224) supplies that edition and its associated data.

[Documentation index](../README.md)
