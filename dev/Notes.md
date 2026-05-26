# Development notes

Those interested in contributing to development are encouraged to so indicate
using [this form](https://docs.google.com/forms/d/e/1FAIpQLSe5rD8X_BpVd9I359ZcoiqN-0E0De1JOvnbr7X3xj22Ca96cg/viewform?usp=publish-editor).

## Versioning

1. First commit all staged files. Then run script 
   `./dev/bump [patch|minor|major]` to bump version number, default `patch` and 
   push the commit and tag to GitHub:
    - `bump-my-version bump [--dry-run --verbose] [major | minor | patch]`
        - [documentation](https://pypi.org/project/bump-my-version/)
        - It correctly finds and updates both the [project] version
          and [tool.bumpversion] current_version, stages the file, commits, and tags.
        - It prints a `* [new tag]` line indicating the local -> remote tag push, 
          not old -> new version tags. 
    - `git push`
        - Earlier ran `git config --global push.followTags true`, so don't need 
          `--follow-tags` in push
        - Automatically updates documentation in GitHub Pages.
2. Optionally, in GitHub: Releases → Draft a new release → choose your tag → write a
   short description → Publish release

Just using `patch` in initial development: Version 0.1.x versions may introduce new
features. After version 0.2.0 significant new features are to have new minor versions
with corresponding release notes. Should start CHANGELOG.md then, if not earlier.

## Publishing

All version changes are tagged and represent releases in the sense that they are to be
*published* (whether or not a corresponding GitHub Release note is created).

To publish:

1. Login to Plotly Cloud
2. In the `Rhythm` app line select settings (the gear widget)
3. `Actions > Update`
4. Click in Drag and Drop box
5. In the pop-up file picker, select and upload all the `app/` folder contents
6. Click `Update`
7. In a few seconds at the top of the revision history list a new version will appear
   with state `Building`, which in several seconds more turns into Running and the
   previous version state turns to Stopped.

## Documentation

All documentation is in `docs/`, published via `Github Pages` using `docsify`.

- Installation: `npm i docsify-cli -g; npm install -g npm@11.15.0`
- To run local preview server: `docsify serve docs`
- [Published view](https://chaynes56.github.io/Rhythm/#/)
- How to add [more pages](https://docsify.js.org/#/more-pages)