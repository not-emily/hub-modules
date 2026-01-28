# Release Hub Modules

Release one or more modules that have uncommitted changes.

## Instructions

Follow these steps **in order**. Do not skip steps or run them out of order.

### Step 1: Detect modules with changes

Run `git status` to find which modules have uncommitted changes. Look for changes in `modules/*/`.

If no modules have changes, inform the user and stop.

### Step 2: For each module with changes

Process each changed module one at a time, completing all steps for one module before moving to the next.

#### 2a. Analyze the changes

For the module, run:
- `git diff modules/<name>/` to see what changed
- Read the current `modules/<name>/manifest.json` to get the current version

#### 2b. Generate release notes

Based on the diff, write a concise summary of what changed. Focus on user-facing changes:
- New features
- Bug fixes
- Improvements
- Breaking changes (if any)

#### 2c. Suggest version bump

Based on the changes, suggest a version bump:
- **patch** (x.y.Z): Bug fixes, small tweaks, documentation, adding patterns
- **minor** (x.Y.0): New features, new tools, new entities, non-breaking enhancements
- **major** (X.0.0): Breaking changes, removed features, changed behavior

Present to the user:
```
## <module-name>

**Current version:** x.y.z
**Suggested bump:** <patch|minor|major> → x.y.z

**Release notes:**
<your generated notes>

Proceed with <patch|minor|major>? (or specify different: patch/minor/major)
```

Wait for user confirmation before proceeding.

#### 2d. Update versions

1. Update `modules/<name>/manifest.json` with the new version
2. Update `registry.json` with the new version and release_tag (`<name>-v<version>`)

#### 2e. Build the release artifact

Run: `./scripts/build-releases.sh <name>`

Verify it succeeds and creates `dist/<name>.zip`.

#### 2f. Commit the changes

Stage only the files for this module:
- `modules/<name>/` (all changed files)
- `registry.json`

Create a commit with a generated message:
```
Release <name> v<version>

<release notes>

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```

Use a HEREDOC for the commit message to preserve formatting.

#### 2g. Tag the release

Run: `git tag <name>-v<version>`

#### 2h. Push to remote

Run: `git push origin main && git push origin <name>-v<version>`

#### 2i. Create GitHub release

Run:
```bash
gh release create <name>-v<version> dist/<name>.zip \
  --title "<name> v<version>" \
  --notes "<release notes>"
```

Use a HEREDOC for the notes if they contain special characters.

#### 2j. Confirm completion

Tell the user:
```
✅ Released <name> v<version>
   https://github.com/.../releases/tag/<name>-v<version>
```

### Step 3: Summary

After all modules are released, provide a summary:
```
## Release Summary

- <module1> v<version> - <one-line summary>
- <module2> v<version> - <one-line summary>

All releases complete.
```

## Important Notes

- Process modules one at a time, completing all steps before moving to the next
- Always wait for user confirmation on the version bump before making changes
- If any step fails, stop and report the error - do not continue to the next module
- The dist/ directory is gitignored - the zip is uploaded to GitHub releases, not committed
