#!/bin/bash
# Generate 3 simulated camera scenes as live HLS (looping test sources).
#
# Scenes 1-3 stay simple test patterns (generic VMS demo feeds).
# Scenes 4-6 are EDGE-ANPR demo scenes: animated traffic with a moving
# license plate that carries READABLE text. The edge ANPR worker OCRs
# these frames (real pixels -> tesseract), so observations, events and
# watchlist alerts come from actual inference - not random generation.
# Plates rotate deterministically through a watchlist-inclusive set.
set -u
OUT=/hls
mkdir -p "$OUT/cam1" "$OUT/cam2" "$OUT/cam3" "$OUT/cam4" "$OUT/cam5" "$OUT/cam6"

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

# ---- Edge-ANPR scenes: readable plates -------------------------------------
# watchlist plates: GJ01AB1234 (CRITICAL), GJ18KB5678, MH12DE9012, GJ27BU4455
# Each plate is visible for 20 s via drawtext's enable=between(t,..) timeline
# option (t = seconds since scene start) - robust, no expression-in-text.
FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

make_plate_scene () {
  local out=$1; local bg=$2
  ffmpeg -re -stream_loop -1 -f lavfi -i "color=c=${bg}:size=640x360:rate=10" \
    -vf "\
drawbox=x=60:y=250:w=520:h=70:color=0x30343c@0.9:t=fill,\
drawtext=fontfile=${FONT}:text='GUJARAT POLICE - EDGE DEMO':fontcolor=0xd8dde6:fontsize=20:x=76:y=266,\
drawtext=fontfile=${FONT}:text='ANPR LANE 1':fontcolor=0x9aa2af:fontsize=14:x=76:y=292,\
drawbox=x=230:y=140:w=260:h=74:color=white:t=fill,\
drawbox=x=230:y=140:w=260:h=74:color=black:t=4,\
drawtext=fontfile=${FONT}:text='GJ01AB1234':fontcolor=black:fontsize=34:x=248:y=158:enable='between(mod(t,80),0,20)',\
drawtext=fontfile=${FONT}:text='GJ18KB5678':fontcolor=black:fontsize=34:x=248:y=158:enable='between(mod(t,80),20,40)',\
drawtext=fontfile=${FONT}:text='MH12DE9012':fontcolor=black:fontsize=34:x=248:y=158:enable='between(mod(t,80),40,60)',\
drawtext=fontfile=${FONT}:text='GJ27BU4455':fontcolor=black:fontsize=34:x=248:y=158:enable='between(mod(t,80),60,80)'" \
    $V -an $HLS "$out" &
}

make_plate_scene "$OUT/cam4/index.m3u8" 0x3a4048 &
P4=$!
make_plate_scene "$OUT/cam5/index.m3u8" 0x424a3e &
P5=$!
make_plate_scene "$OUT/cam6/index.m3u8" 0x39424e &
P6=$!

wait $P1 $P2 $P3 $P4 $P5 $P6
