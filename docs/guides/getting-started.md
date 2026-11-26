# Install and verify CrossTalk

The package supports Python 3.13 and newer. The repository selects Python 3.15.2 in [`.python-version`](../../.python-version). Install uv and run these commands in a shell. [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)

```sh
git clone https://github.com/docxology/CrossTalk-study.git
cd CrossTalk-study
uv sync --locked
uv run --locked crosstalk --help
uv run --locked pytest
```

The tests construct synthetic inputs and run without historical scans. For a command's parameters, run `uv run --locked crosstalk COMMAND --help`. Commands with `--root` use that directory for source and generated files. The default is the shell's working directory.

Use the [corpus workflow](corpus.md) for inputs and output locations. The [manuscript reproduction guide](../reproduction/manuscript.md) verifies the study PDF without PDF acquisition.

[Documentation index](../README.md)
