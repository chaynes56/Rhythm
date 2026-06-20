# Claude Code project configuration

This directory ships shared [Claude Code](https://code.claude.com) settings for the repo.
Everyone who clones gets the same automated checks — no machine-specific paths.

## What's here

| File | Purpose | Committed? |
| --- | --- | --- |
| `settings.json` | Shared project settings (the ruff hook). | ✅ yes |
| `hooks/ruff-posttooluse.sh` | Runs `ruff check` after Claude edits a `.py` file (POSIX `sh`). | ✅ yes |
| `settings.local.json` | Your personal overrides (model, status line, etc.). | ❌ gitignore it |

## One-time setup after cloning

The hook is invoked as `sh .../ruff-posttooluse.sh`, so it runs regardless of
whether the executable bit survived the clone — **no `chmod` needed**. The
script is POSIX `sh`-compatible, so it works whether your `/bin/sh` is bash,
dash, or zsh.

Just make sure [`ruff`](https://docs.astral.sh/ruff/) is installed and on your `PATH`:

```bash
# pick one
pipx install ruff
uv tool install ruff
brew install ruff
```

If `ruff` isn't found, the hook degrades gracefully — it warns once and lets the
edit through rather than blocking you.

## How it works

After Claude edits or writes a file (`Edit`/`Write`), Claude Code runs
`hooks/ruff-posttooluse.sh`, passing a JSON payload on **stdin**. The script
pulls `tool_input.file_path` out of that payload, and if it's an existing
`.py` file, runs `ruff check` on it. Lint findings are sent back to Claude
(exit code 2) so it can fix them in the same turn.

The path is resolved via `$CLAUDE_PROJECT_DIR`, which Claude Code sets to the
repo root — that's what keeps this portable across machines and checkout
locations.

## Personal settings stay out of the repo

Things like your preferred `model` or a custom `statusLine` are personal, not
project behavior. Put those in `.claude/settings.local.json` (which should be
gitignored), for example:

```json
{
  "model": "opusplan",
  "statusLine": {
    "type": "command",
    "command": "sh $HOME/.claude/statusline-command.sh"
  }
}
```

Claude Code merges user, project, and local settings, so your local file layers
on top of the shared `settings.json` without anyone needing to touch it.

## Customizing the hook

- Lint **and** auto-fix: change `ruff check "$file_path"` to
  `ruff check --fix "$file_path"` in the script.
- Add formatting: append a `ruff format "$file_path"` line.
- `ruff` lives in a virtualenv: set `RUFF="uv run ruff"` near the top of the script.
