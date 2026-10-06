#!/usr/bin/env bash
# Executa a atualizacao uma vez (uso local).
set -e
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
python3 update_playlist.py --workers 40 --timeout 8
echo "Listas atualizadas em ./playlists/"
