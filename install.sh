#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"
target="$plugin_dir/denis.yoinker"
omarchy plugin validate "$source_dir"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/yoinker"
mkdir -p "$plugin_dir" "$state_dir"
stage_root=$(mktemp -d "$state_dir/.install-XXXXXX")
stage="$stage_root/denis.yoinker"
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
# Let the automatic file-watcher reload settle before asking that same shell
# process to restart itself.
for _ in {1..12}; do
  if timeout 2 omarchy-shell shell ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
omarchy restart shell
for _ in {1..12}; do
  if timeout 2 omarchy-shell shell ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if [[ -d "$plugin_dir/denis.media-downloader" ]]; then
  omarchy plugin disable denis.media-downloader
fi
omarchy plugin enable denis.yoinker --section right
