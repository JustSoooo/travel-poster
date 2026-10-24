#!/bin/bash
# 旅行海报 · 终端一键版（macOS / Linux）
#   第一次：自动装好需要的东西（Python 环境、exiftool、截图用的浏览器），装在 ~/.travel-poster，不动系统
#   然后：选照片所在的硬盘/文件夹 → 扫描 → 确认设备 → 四张海报出现在「桌面/旅行海报」
# 用法：
#   curl -fsSL https://github.com/JustSoooo/travel-poster/raw/main/tp.sh | bash
#   或者下载仓库后：bash tp.sh [照片文件夹]
set -e
HOME_DIR="$HOME/.travel-poster"
APP="$HOME_DIR/app"
VENV="$HOME_DIR/venv"
REPO="https://github.com/JustSoooo/travel-poster"
mkdir -p "$HOME_DIR"
say() { printf "\033[1m%s\033[0m\n" "$*"; }
ask() { local v=""; read -r -p "$1" v < /dev/tty 2>/dev/null || true; echo "$v"; }

say "旅行海报 · 终端版"

# ---------- 程序本体：从仓库目录运行就用当前目录，否则下载/更新到 ~/.travel-poster/app ----------
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SRC" ] && [ -f "$SRC/app/cli.py" ]; then
  APP="$SRC"
else
  say "下载程序…"
  tmp="$(mktemp -d)"
  curl -fL --retry 3 -o "$tmp/tp.tar.gz" "$REPO/archive/refs/heads/main.tar.gz"
  rm -rf "$APP"; mkdir -p "$APP"; tar -xzf "$tmp/tp.tar.gz" -C "$APP" --strip-components 1; rm -rf "$tmp"
fi

# ---------- Python ----------
PY=""
for c in python3.12 python3.11 python3.13 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  say "没找到 Python 3。"
  if [ "$(uname)" = "Darwin" ]; then echo "Mac 上运行一次：xcode-select --install （弹窗点安装，装完再运行本脚本）"; fi
  exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  say "第一次运行：准备 Python 环境（约 2–5 分钟）…"
  "$PY" -m venv "$VENV"
fi
STAMP="$VENV/.req-$(cksum < "$APP/requirements-cli.txt" | cut -d' ' -f1)"
if [ ! -f "$STAMP" ]; then
  "$VENV/bin/python" -m pip install -q --upgrade pip || true
  if ! "$VENV/bin/python" -m pip install -q -r "$APP/requirements-cli.txt"; then
    say "默认源太慢，换清华镜像重试…"
    "$VENV/bin/python" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r "$APP/requirements-cli.txt"
  fi
  touch "$STAMP"
fi

# ---------- exiftool（读照片拍摄信息）----------
if ! command -v exiftool >/dev/null 2>&1; then
  if [ ! -x "$HOME_DIR/exiftool/exiftool" ]; then
    say "安装 exiftool…"
    tmp="$(mktemp -d)"
    if ! curl -fL --retry 3 -o "$tmp/et.tar.gz" "https://github.com/exiftool/exiftool/archive/refs/heads/master.tar.gz"; then
      ver="$(curl -fsSL https://exiftool.org/ver.txt)"
      curl -fL --retry 3 -o "$tmp/et.tar.gz" "https://exiftool.org/Image-ExifTool-$ver.tar.gz" || { say "exiftool 下载失败，检查网络后重试"; exit 1; }
    fi
    rm -rf "$HOME_DIR/exiftool"; mkdir -p "$HOME_DIR/exiftool"
    tar -xzf "$tmp/et.tar.gz" -C "$HOME_DIR/exiftool" --strip-components 1; rm -rf "$tmp"
  fi
  export PATH="$HOME_DIR/exiftool:$PATH"
fi

# ---------- 截图用的浏览器：有 Chrome 就直接用，没有再下载 ----------
CHROME=""
for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
         "$(command -v google-chrome 2>/dev/null)" "$(command -v chromium 2>/dev/null)" "$(command -v chromium-browser 2>/dev/null)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
done
if [ -n "$CHROME" ]; then
  export CHROMIUM_PATH="$CHROME"
elif [ ! -f "$HOME_DIR/.chromium-ok" ]; then
  say "下载截图用的浏览器（约 150 MB，只需一次）…"
  export PLAYWRIGHT_BROWSERS_PATH="$HOME_DIR/browsers"
  if ! "$VENV/bin/python" -m playwright install chromium; then
    say "换国内镜像重试…"
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright "$VENV/bin/python" -m playwright install chromium
  fi
  touch "$HOME_DIR/.chromium-ok"
fi
export PLAYWRIGHT_BROWSERS_PATH="$HOME_DIR/browsers"

# ---------- 选照片文件夹 ----------
ROOT="$1"
if [ -z "$ROOT" ]; then
  LAST="$(cat "$HOME_DIR/last_root" 2>/dev/null || true)"
  if [ -n "$LAST" ] && [ -d "$LAST" ]; then
    v="$(ask "上次用的是：$LAST  直接回车沿用，或输入 n 重新选：")"
    [ "$v" != "n" ] && ROOT="$LAST"
  fi
fi
if [ -z "$ROOT" ]; then
  VOLS=()
  if [ "$(uname)" = "Darwin" ]; then
    for v in /Volumes/*; do [ -d "$v" ] && [ "$(basename "$v")" != "Macintosh HD" ] && [ ! -L "$v" ] && VOLS+=("$v"); done
  else
    for v in /media/"$USER"/* /mnt/*; do [ -d "$v" ] && VOLS+=("$v"); done
  fi
  echo
  say "照片在哪？"
  i=1; for v in "${VOLS[@]}"; do echo "  $i) $v"; i=$((i+1)); done
  echo "  也可以把照片文件夹直接拖进这个窗口，然后回车"
  v="$(ask "> ")"
  v="${v%"${v##*[![:space:]]}"}"; v="${v#\'}"; v="${v%\'}"; v="${v//\\ / }"
  if [[ "$v" =~ ^[0-9]+$ ]] && [ "$v" -ge 1 ] && [ "$v" -le "${#VOLS[@]}" ]; then ROOT="${VOLS[$((v-1))]}"; else ROOT="$v"; fi
fi
if [ ! -d "$ROOT" ]; then say "找不到文件夹：$ROOT"; exit 1; fi
echo "$ROOT" > "$HOME_DIR/last_root"

if { true < /dev/tty; } 2>/dev/null; then
  "$VENV/bin/python" "$APP/app/cli.py" "$ROOT" --data "$HOME_DIR/data" < /dev/tty
else
  "$VENV/bin/python" "$APP/app/cli.py" "$ROOT" --data "$HOME_DIR/data" --yes
fi
