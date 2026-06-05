# Rhythm Analyzer Development Notes

This is an open source project with [Github repo](https://github.com/chaynes56/Rhythm)
and [user documentation](https://chaynes56.github.io/Rhythm/#/).

Those interested in contributing to development are encouraged to so indicate and
provide contact email using
[this form](https://docs.google.com/forms/d/e/1FAIpQLSe5rD8X_BpVd9I359ZcoiqN-0E0De1JOvnbr7X3xj22Ca96cg/viewform?usp=publish-editor).

## Setup

1. Install `uv`, this project's recommended Python dependency manager.
    - Use `brew install uv`, `pipx install uv`, or similar depending on your preferred
      system package manager.
2. Clone or fork the repo and `cd` into it.
3. `uv sync` to create in `.venv` the project virtual environment and install
   dependencies as `pyproject.toml` specifies. This also creates a `uv.lock` file to
   track exact versions.
4. `source .venv/bin/activate`
    - Within the project, `python` and `plotly` commands then run the project versions.

## Check for Plotly cloud python version update

Do this periodically to ensure the app's Plotly cloud server is running the latest
Python version that it supports, and update the local environment as needed to match.

1. Login
   to [Plotly Cloud](https://cloud.plotly.com/app/7cfb3e1c-4795-4466-8dff-29677836cf73/settings?tab=general)
2. `General > Python version` and select the most current version. If this is not the
   same as `pyproject.toml`'s `requires-python`:
    1. Update `requires-python` to the new version
    2. Run `uv venv --python 3.13 && uv sync` to update the local venv
    3. Smoke test the local version
    4. Create and publish a new version as follows.

## Versioning

1. If there have been any changes in `dev/assets`, update the embedded samples with
   `./dev/embed_samples.py`.
2. Commit all staged files. Then run script
   `./dev/bump [patch|minor|major]` to bump version number, default `patch` and push the
   commit and tag to GitHub. Only `patch` has been used in initial development, so
   `0.1.x` versions may introduce new features. After version `0.2.0`, significant new
   features are to have a new minor version. `dev/bump` does the following:
    - `bump-my-version bump [--dry-run --verbose] [major | minor | patch]`
        - [documentation](https://pypi.org/project/bump-my-version/)
        - It correctly finds and updates both the [project] version
          and [tool.bumpversion] current_version, stages the file, commits, and tags.
        - It prints a `* [new tag]` line indicating the local -> remote tag push, not
          old -> new version tags.
    - `git push`
        - Earlier ran `git config --global push.followTags true`, so don't need
          `--follow-tags` in push
        - Automatically updates documentation in GitHub Pages.
2. Optionally for patch releases, always for others, in GitHub: `Releases → Draft a new 
   release → choose your tag →` write a short description `→ Publish release`. This
   makes it easy to track major and minor releases.
3. Starting with version `0.2.0`, for minor and major releases add release notes in
   `CHANGELOG.md`, including the version number and corresponding tag. This is also
   recommended for significant patch releases.

## Publishing

All version changes are tagged and represent releases in the sense that they are to be
*published* (whether or not a corresponding GitHub Release note is created). Publishinig
may be accomplished via the CLI commands that follow or via the Plotly cloud interface
used in the `Check for Plotly cloud python version update` section above (upload all the
`app/` files except thoes beginning with `__`). Note that the maximum upload size is 80
MiB via the web interface vs 200 MiB via CLI, so at some point the CLI method may be the
only option.

Run `./dev/publish` to publish the current version, and wait a while for the Publish
Status to be `Running`. You may be asked to authenticate with the Plotly cloud. A
verification URL is provided with a device code. Follow the URL and confirm the device
code to complete authentication.

The `publish` script does the following:

1. `cd app`
2. `plotly user login`
3. `plotly app publish --name Rhythm`

`plotly --help` and `plotly app publish --help` list other options, including
`plotly app status`, which may be useful to confirm that the app is running.

## Documentation

All documentation is in `docs/`, published via `Github Pages` using `docsify`. The 
[documentation page](https://chaynes56.github.io/Rhythm/#/) formats the `docs/*.md` 
files on the fly, so documentation changes are published when pushed.

- [Docsify documentation](https://docsify.js.org/#/?id=docsify)
- Installation: `npm i docsify-cli -g; npm install -g npm@11.15.0`
- To run local preview server: `docsify serve docs`
- How to add [more pages](https://docsify.js.org/#/more-pages)