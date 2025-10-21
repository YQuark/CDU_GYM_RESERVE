#!/usr/bin/env bash
# 简易截图脱敏脚本：对指定目录下的 PNG/JPG 文件执行模糊处理或覆盖文本。
# 依赖 ImageMagick（convert）或相同能力的工具。示例脚本仅用于提交材料说明。

set -euo pipefail

dir=${1:-screenshots}
mkdir -p "${dir}"

echo "[scrub] 将对目录 ${dir} 下的 PNG/JPG 文件执行占位覆盖"
for file in "${dir}"/*.{png,PNG,jpg,JPG,jpeg,JPEG}; do
  [ -e "$file" ] || continue
  tmp="${file}.tmp.png"
  convert "$file" -fill '#1f2937' -draw "rectangle 0,0 400,60" "$tmp"
  convert "$tmp" -gravity Northwest -pointsize 28 -fill '#f8fafc' -annotate +20+30 '示例数据 / <REDACTED>' "$file"
  rm -f "$tmp"
  echo "[scrub] processed $file"
  done

echo "[scrub] 完成。请人工复核截图是否符合提交要求。"
