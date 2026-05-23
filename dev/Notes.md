# Development notes

## Versioning

- uvx bump-my-version [major | minor | patch]
  - [documentation](https://pypi.org/project/bump-my-version/)
  -  It correctly finds and updates both the [project] version and [tool.bumpversion] 
     current_version, stages the file, commits, and tags.

## Documentation
All documentation in `docs/`, published on Github Pages using docsify.
- `npm i docsify-cli -g; npm install -g npm@11.15.0`
- [More pages](https://docsify.js.org/#/more-pages) also for sidebars
- `docsify serve docs` for preview on `http://localhost:3000`