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
      "release_tag": "recipes-v1.1.0",
      "description": "Manage recipes, grocery lists, pantry, and meal planning",
      "keywords": ["recipe", "cooking", "groceries", "meal", "food"]
    }
  ]
}
```

Each module has its own `release_tag` pointing to its GitHub release. This allows modules to be versioned and released independently.

## Releasing a Module

### 1. Update the module

Make your changes in `modules/{name}/` and bump the version in `manifest.json`:

```json
{
  "name": "recipes",
  "version": "1.2.0",
  ...
}
```

### 2. Build the release artifact

```bash
./scripts/build-releases.sh recipes
```

This creates `dist/recipes.zip` and shows you the release tag.

### 3. Update the registry

Edit `registry.json` to update the module's version and release_tag:

```json
{
  "name": "recipes",
  "version": "1.2.0",
  "release_tag": "recipes-v1.2.0",
  ...
}
```

### 4. Commit and tag

```bash
git add .
git commit -m "Release recipes v1.2.0"
git tag recipes-v1.2.0
git push origin main
git push origin recipes-v1.2.0
```

### 5. Create GitHub release

```bash
gh release create recipes-v1.2.0 dist/recipes.zip --title "recipes v1.2.0"
```

Or create the release manually on GitHub and upload the zip file.

## Adding a New Module

1. Create the module directory: `modules/{name}/`
2. Add `manifest.json` with required fields (name, version, description, keywords, tools)
3. Add tool scripts in `tools/`
4. Optionally add `assistants.json` for assistant templates
5. Add an entry to `registry.json`
6. Follow the release process above

## Module Structure

Each module must have:

- `manifest.json` - Module metadata, tools, and routing info
- `tools/` - Executable scripts for each tool

Optional:
- `assistants.json` - Pre-built assistant templates

See [hub-core module guide](https://github.com/not-emily/hub-core/blob/main/docs/guides/creating-modules.md) for full documentation.

## Build Script

```bash
# Build a single module
./scripts/build-releases.sh recipes

# Build all modules (useful for verification)
./scripts/build-releases.sh --all
```
