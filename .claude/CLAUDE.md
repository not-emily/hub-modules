# Claude Context - hub-modules

This file provides context for Claude Code sessions.

## Project Overview

First-party modules for Hub. Each module provides tools, entities, and routing for a specific domain (recipes, notes, etc.). Modules are independent from hub-core and can be installed/released separately.

## Tech Stack

- **Tool scripts:** Bash (some Python)
- **Data format:** JSON
- **Primitives/Utilities:** Provided by hub-core via `$HUB_PRIMITIVES` and `$HUB_UTILITIES`
- **Dependencies:** jq for JSON parsing in bash scripts

## Key Patterns & Conventions

- **Entities** define routing - aliases map natural language to internal names, actions map to tools
- **Tools** are generic scripts that receive an `entity` param to know which data file to use
- **Data files** are stored at `$HUB_USER_DATA/<entity>.json`
- **Naming:** lowercase with underscores (e.g., `grocery_list`, `add_item`)
- **Each module versioned independently** with its own release tag (e.g., `recipes-v1.2.0`)

## Important Context

- Read `../hub-core/docs/guides/creating-modules.md` for the full module development guide
- Use `/module-expert` to load development context at session start
- Use `/release` to automate the release process
- Modules never modify hub-core - everything is declared in manifest.json

## Project Structure

```
hub-modules/
├── registry.json              # Index of available modules (version + release_tag)
├── modules/
│   └── recipes/               # Example module
│       ├── manifest.json      # Module definition (entities, tools, fast_match)
│       ├── assistants.json    # Optional assistant templates
│       └── tools/             # Executable tool scripts
├── scripts/
│   └── build-releases.sh      # Build module zip artifacts
└── dist/                      # Built artifacts (gitignored, uploaded to GH releases)
```

## Slash Commands

- `/module-expert` - Load context for module development (add `--design` for full Hub architecture)
- `/release` - Detect changes, generate release notes, handle full release flow

## Helper Scripts

- `./scripts/build-releases.sh <module>` - Build a module's release artifact
- `./scripts/build-releases.sh --all` - Build all modules
