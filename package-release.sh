#!/usr/bin/env bash
set -euo pipefail

if (( $# != 2 )) || [[ ! "$1" =~ ^[[:alnum:]][[:alnum:]._-]*$ ]]; then
    echo "Usage: bash package-release.sh <version> <output-directory>" >&2
    exit 2
fi

version=$1
mkdir -p -- "$2"
output_dir=$(cd -- "$2" && pwd)
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bundle="3dlife-manager-${version}"
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT
tmp_archive=$(mktemp -- "$output_dir/.${bundle}.XXXXXX.tar.gz")
trap 'rm -rf -- "$staging"; rm -f -- "$tmp_archive"' EXIT

(
    cd "$repo_dir/frontend"
    npm run build
)

package="$staging/$bundle"
mkdir -p "$package/backend" "$package/frontend" "$package/service"
cp -- "$repo_dir/README.md" "$repo_dir/instal.sh" "$package/"
cp -- "$repo_dir/backend/"{app.py,sdbus_utils.py,requirements.txt} "$package/backend/"
cp -- "$repo_dir/service/"{3dlife-manager,wifi-manager.service} "$package/service/"
cp -a -- "$repo_dir/frontend/dist" "$package/frontend/"
test -s "$package/frontend/dist/index.html"

tar -czf "$tmp_archive" -C "$staging" "$bundle"
chmod 644 "$tmp_archive"
mv -T -- "$tmp_archive" "$output_dir/$bundle.tar.gz"
printf '%s\n' "$output_dir/$bundle.tar.gz"
