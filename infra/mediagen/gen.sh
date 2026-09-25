#!/bin/bash
# Generate 3 simulated camera scenes as live HLS (looping test sources).
set -u
OUT=/hls
mkdir -p "$OUT/cam1" "$OUT/cam2" "$OUT/cam3"

V="-c:v libx264 -preset veryfast -tune zerolatency -g 30 -sc_threshold 0 -pix_fmt yuv420p"
HLS="-f hls -hls_time 2 -hls_list_size 12 -hls_flags delete_segments+omit_endlist+append_list"

ffmpeg -re -stream_loop -1 -f lavfi -i "testsrc2=size=640x360:rate=15" \
  $V -an $HLS "$OUT/cam1/index.m3u8" &
P1=$!

ffmpeg -re -stream_loop -1 -f lavfi -i "smptehdbars=size=640x360:rate=15" \
  $V -an $HLS "$OUT/cam2/index.m3u8" &
P2=$!

ffmpeg -re -stream_loop -1 -f lavfi -i "mandelbrot=size=640x360:rate=12" \
  $V -an $HLS "$OUT/cam3/index.m3u8" &
P3=$!

wait $P1 $P2 $P3
