#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"
target="$plugin_dir/denis.yoinker"
omarchy plugin validate "$source_dir"
if [[ -d "$target" ]]; then
  backup_dir="${XDG_STATE_HOME:-$HOME/.local/state}/yoinker/backups/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"
  cp -a -- "$target" "$backup_dir/"
fi
mkdir -p "$target"
for file in manifest.json BarWidget.qml Configuration.qml backend.py download.py settings.py spotify.py music.py lookup.py; do
  cp -- "$source_dir/$file" "$target/$file"
done
omarchy-shell shell rescanPlugins
if [[ -d "$plugin_dir/denis.media-downloader" ]]; then
  omarchy plugin disable denis.media-downloader
fi
omarchy plugin enable denis.yoinker --section right
