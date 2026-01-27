# hub-modules

First-party modules for Hub.

## Structure

```
hub-modules/
├── registry.json           # Index of available modules
├── modules/
│   └── recipes/            # Recipe and meal planning module
│       ├── manifest.json
│       ├── assistants.json
│       └── tools/
└── scripts/
    └── build-releases.sh   # Build release artifacts
```

## Registry

The `registry.json` file lists all modules available for installation. Station admins use this to browse and install modules.

```json
{
  "version": "1",
  "modules": [
    {
      "name": "recipes",
      "version": "1.1.0",
      "description": "Manage recipes, grocery lists, pantry, and meal planning",
      "keywords": ["recipe", "cooking", "groceries", "meal", "food"]
    }
  ]
}
```

## Publishing a Module

1. Develop the module in `modules/{name}/`
2. Ensure `manifest.json` has a `version` field
3. Update `registry.json` with the module entry
4. Commit and push to main
5. Create a release:

```bash
# Build zip artifacts
./scripts/build-releases.sh v2025.01.27

# Tag and release
git tag v2025.01.27
git push origin v2025.01.27
gh release create v2025.01.27 dist/*.zip --title "v2025.01.27"
```

## Module Structure

Each module must have:

- `manifest.json` - Module metadata, tools, and routing info
- `tools/` - Executable scripts for each tool

Optional:
- `assistants.json` - Pre-built assistant templates

See [hub-core docs](https://github.com/not-emily/hub-core/blob/main/docs/guides/creating-modules.md) for full module development guide.
