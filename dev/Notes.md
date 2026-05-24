# Development notes

Those interested in contributing to development are encouraged to so indicate
using [this form](https://docs.google.com/forms/d/e/1FAIpQLSe5rD8X_BpVd9I359ZcoiqN-0E0De1JOvnbr7X3xj22Ca96cg/viewform?usp=publish-editor).

## Versioning

- `bump-my-version bump [--dry-run -verbose] [major | minor | patch]`
    - [documentation](https://pypi.org/project/bump-my-version/)
    - It correctly finds and updates both the [project] version and [tool.bumpversion]
      current_version, stages the file, commits, and tags.

## Documentation

All documentation is in `docs/`, published via `Github Pages` using `docsify`.

- `npm i docsify-cli -g; npm install -g npm@11.15.0`
- [More pages](https://docsify.js.org/#/more-pages) also for sidebars
- `docsify serve docs` for preview on `http://localhost:3000`
- [Published view](https://chaynes56.github.io/Rhythm/#/)