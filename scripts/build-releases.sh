#!/bin/bash
#
# build-releases.sh - Build zip artifacts for modules
#
# Usage:
#   ./scripts/build-releases.sh <module>     # Build one module
#   ./scripts/build-releases.sh --all        # Build all modules
#
# Examples:
#   ./scripts/build-releases.sh recipes      # Build recipes.zip
#   ./scripts/build-releases.sh --all        # Build all module zips
#
# Creates zip files in dist/ that can be attached to GitHub releases.

set -e

TARGET="${1:-}"

if [[ -z "$TARGET" ]]; then
    echo "Usage: $0 <module>     # Build one module"
    echo "       $0 --all        # Build all modules"
    echo ""
    echo "Examples:"
    echo "  $0 recipes"
    echo "  $0 --all"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MODULES_DIR="$REPO_ROOT/modules"
DIST_DIR="$REPO_ROOT/dist"

# Ensure dist directory exists
mkdir -p "$DIST_DIR"

# Build a single module
build_module() {
    local module_name="$1"
    local module_dir="$MODULES_DIR/$module_name"

    if [[ ! -d "$module_dir" ]]; then
        echo "Error: Module '$module_name' not found in $MODULES_DIR"
        exit 1
    fi

    if [[ ! -f "$module_dir/manifest.json" ]]; then
        echo "Error: Module '$module_name' has no manifest.json"
        exit 1
    fi

    # Get version from manifest
    local version
    version=$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$module_dir/manifest.json" | head -1 | sed 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

    if [[ -z "$version" ]]; then
        echo "Error: Could not read version from $module_name/manifest.json"
        exit 1
    fi

    local zip_file="$DIST_DIR/${module_name}.zip"
    local release_tag="${module_name}-v${version}"

    echo "Building: $module_name v$version"
    echo "  Tag: $release_tag"

    # Remove old zip if exists
    rm -f "$zip_file"

    # Create zip from module directory
    (cd "$MODULES_DIR" && zip -r "$zip_file" "$module_name" -x "*.DS_Store" -x "*/__pycache__/*")

    echo "  Created: $zip_file"
    echo ""
    echo "To release:"
    echo "  1. Update registry.json with version '$version' and release_tag '$release_tag'"
    echo "  2. git add . && git commit -m \"Release $module_name v$version\""
    echo "  3. git tag $release_tag"
    echo "  4. git push origin main && git push origin $release_tag"
    echo "  5. gh release create $release_tag dist/${module_name}.zip --title \"$module_name v$version\""
}

# Build all modules
build_all() {
    echo "Building all modules"
    echo "===================="
    echo ""

    local count=0
    for module_dir in "$MODULES_DIR"/*/; do
        if [[ ! -d "$module_dir" ]]; then
            continue
        fi

        local module_name
        module_name=$(basename "$module_dir")

        # Skip directories starting with underscore
        if [[ "$module_name" == _* ]]; then
            continue
        fi

        # Skip if no manifest
        if [[ ! -f "$module_dir/manifest.json" ]]; then
            echo "Warning: Skipping $module_name (no manifest.json)"
            continue
        fi

        local version
        version=$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$module_dir/manifest.json" | head -1 | sed 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

        local zip_file="$DIST_DIR/${module_name}.zip"

        echo "Building: $module_name v$version"

        rm -f "$zip_file"
        (cd "$MODULES_DIR" && zip -rq "$zip_file" "$module_name" -x "*.DS_Store" -x "*/__pycache__/*")

        echo "  Created: $zip_file"
        ((count++))
    done

    echo ""
    echo "===================="
    echo "Built $count module(s) in $DIST_DIR"
}

# Main
if [[ "$TARGET" == "--all" ]]; then
    build_all
else
    build_module "$TARGET"
fi
