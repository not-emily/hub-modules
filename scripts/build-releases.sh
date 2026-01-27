#!/bin/bash
#
# build-releases.sh - Build zip artifacts for all modules
#
# Usage: ./scripts/build-releases.sh <version>
# Example: ./scripts/build-releases.sh v2025.01.27
#
# Creates a zip file for each module in dist/
# These zips can be attached to a GitHub release.

set -e

VERSION="${1:-}"

if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 v2025.01.27"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MODULES_DIR="$REPO_ROOT/modules"
DIST_DIR="$REPO_ROOT/dist"

# Clean and create dist directory
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "Building release artifacts for $VERSION"
echo "========================================="
echo ""

# Build zip for each module
for module_dir in "$MODULES_DIR"/*/; do
    if [[ ! -d "$module_dir" ]]; then
        continue
    fi

    module_name=$(basename "$module_dir")

    # Skip directories starting with underscore
    if [[ "$module_name" == _* ]]; then
        continue
    fi

    # Verify manifest exists
    if [[ ! -f "$module_dir/manifest.json" ]]; then
        echo "Warning: Skipping $module_name (no manifest.json)"
        continue
    fi

    zip_file="$DIST_DIR/${module_name}.zip"

    echo "Building: $module_name -> ${module_name}.zip"

    # Create zip from module directory
    (cd "$MODULES_DIR" && zip -r "$zip_file" "$module_name" -x "*.DS_Store" -x "*/__pycache__/*")

    echo "  Created: $zip_file"
done

echo ""
echo "========================================="
echo "Build complete. Artifacts in: $DIST_DIR"
echo ""
echo "To create a GitHub release:"
echo "  1. git tag $VERSION"
echo "  2. git push origin $VERSION"
echo "  3. gh release create $VERSION dist/*.zip --title \"$VERSION\" --notes \"Release $VERSION\""
echo ""
echo "Or manually upload the zip files to the GitHub release page."
