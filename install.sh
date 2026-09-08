#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"
target="$plugin_dir/denis.yoink"
omarchy plugin validate "$source_dir"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/yoink"
mkdir -p "$plugin_dir" "$state_dir"
stage_root=$(mktemp -d "$state_dir/.install-XXXXXX")
stage="$stage_root/denis.yoink"
mkdir -p "$stage"
trap 'rm -rf -- "$stage_root"' EXIT
for file in manifest.json Service.qml BarWidget.qml Configuration.qml backend.py download.py settings.py spotify.py music.py lookup.py games.py; do
  cp -- "$source_dir/$file" "$stage/$file"
done
if [[ -d "$target" ]]; then
  backup_dir="$state_dir/backups/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"
  mv -- "$target" "$backup_dir/"
fi
mv -- "$stage" "$target"
# A fresh registry load avoids stale QML component URLs after the atomic swap.
# The shell manages its own startup; do not poll it from the installer.
omarchy restart shell || true
sleep 3
if [[ -d "$plugin_dir/denis.media-downloader" ]]; then
  omarchy plugin disable denis.media-downloader
fi
omarchy plugin enable denis.yoink --section right
