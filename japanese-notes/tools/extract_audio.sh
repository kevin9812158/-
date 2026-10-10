#!/bin/sh
# 用法：sh extract_audio.sh 影片1 [影片2 ...]
# 在影片旁邊產生同名 .m4a（單聲道 96kbps，一小時約 43MB，符合 Plaud 500MB 上限）。
# 需要 ffmpeg：Mac 用 brew install ffmpeg
command -v ffmpeg >/dev/null || { echo "找不到 ffmpeg。Mac 請先執行：brew install ffmpeg"; exit 1; }
[ $# -gt 0 ] || { echo "用法：sh extract_audio.sh 影片檔"; exit 1; }
for f in "$@"; do
  out="${f%.*}.m4a"
  echo "處理中：$f"
  if ffmpeg -hide_banner -loglevel error -stats -y -i "$f" -vn -ac 1 -c:a aac -b:a 96k "$out"; then
    size=$(wc -c < "$out")
    echo "完成：$out（$((size / 1048576)) MB）"
    if [ "$size" -gt 524288000 ]; then echo "注意：超過 500MB，Plaud 可能不收。"; fi
  else
    echo "失敗：$f"
  fi
done
