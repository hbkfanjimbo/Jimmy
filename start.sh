#!/bin/bash
# One-command setup + run for macOS (also works on Linux).
#   bash start.sh              -> build or update the whole archive
#   bash start.sh --limit 3    -> quick test with 3 videos
# Any extra options are passed to archive.py (see: bash start.sh --help).
set -e
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# 1) uv: a small tool that installs the right Python and packages for us
#    (no admin password needed; everything stays in your home folder).
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (one time)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# 2) A private Python environment for this folder, with yt-dlp kept up to date
#    (YouTube changes often; new yt-dlp versions keep up). deno is the
#    JavaScript runtime yt-dlp needs for YouTube.
if [ ! -x .venv/bin/python ]; then
  echo "Creating Python environment (one time)..."
  uv venv --python 3.12 .venv
fi
echo "Updating yt-dlp..."
uv pip install --quiet --python .venv/bin/python -U "yt-dlp[default]" deno

export PATH="$PWD/.venv/bin:$PATH"

# 3) Run. caffeinate keeps the Mac awake while it works (macOS only).
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i .venv/bin/python archive.py "$@"
else
  .venv/bin/python archive.py "$@"
fi

if [ "$(uname)" = "Darwin" ] && [ -d chatgpt_upload ]; then
  open chatgpt_upload
fi
