#!/bin/bash
set -euo pipefail

PASSWORD="8XDQ2R9Z7V3B4W5C6X7Y8Z9"

BASE_DIR=/app/varsea
mkdir -p "$BASE_DIR"

for sub in tmp data logs backup cfg; do
  DIR="$BASE_DIR/$sub-$(head -c4 /dev/urandom | od -An -tx4 | tr -d ' ')"
  mkdir -p "$DIR"
  dd if=/dev/urandom of="$DIR/$(date +%s%N).bin" bs=512 count=10 status=none
  echo "Dummy entry at $(date +'%Y-%m-%d %H:%M:%S')" > "$DIR/$(date +%Y%m%d-%H%M%S).log"
done

IMG_DIR=/app/varsea/disks/sub1/subA/subAlpha
mkdir -p "$IMG_DIR"
IMG_PATH="$IMG_DIR/ae3f4c.dat"

dd if=/dev/urandom of="$IMG_PATH" bs=1M count=4 status=none

echo "PASSWORD=$PASSWORD" > /app/launchcode.txt
zip /app/secret.zip /app/launchcode.txt > /dev/null

offset=$(strings -t d /app/secret.zip | grep PASSWORD= | awk '{print $1}')

FRAG_DIR=/tmp/fragments
mkdir -p "$FRAG_DIR"

pos1=$((512 * 1024))
pos2=$((18 * 1048576 / 10))
pos3=$((25 * 1048576 / 10))
pos4=$((33 * 1048576 / 10))

dd if=/app/secret.zip of="$FRAG_DIR/part1" bs=1 skip="$offset" count=16 status=none
dd if=/app/secret.zip of="$FRAG_DIR/part2" bs=1 skip=$((offset + 10)) count=19 status=none
dd if=/app/secret.zip of="$FRAG_DIR/part3" bs=1 skip=$((offset + 20)) count=21 status=none
dd if=/app/secret.zip of="$FRAG_DIR/part4" bs=1 skip=$((offset + 35)) count=21 status=none

dd if="$FRAG_DIR/part1" of="$IMG_PATH" bs=1 seek="$pos1" conv=notrunc status=none
dd if="$FRAG_DIR/part2" of="$IMG_PATH" bs=1 seek="$pos2" conv=notrunc status=none
dd if="$FRAG_DIR/part3" of="$IMG_PATH" bs=1 seek="$pos3" conv=notrunc status=none
dd if="$FRAG_DIR/part4" of="$IMG_PATH" bs=1 seek="$pos4" conv=notrunc status=none

for n in 1 2 3 4; do
  noise_pos_var="pos$n"
  noise_pos=$((${!noise_pos_var} - 2048))
  [ "$noise_pos" -lt 0 ] && noise_pos=0
  echo "system audit $(date +'%Y-%m-%d %H:%M:%S') pass=NOISE_BLOCK_$n status=ok" > /tmp/noise_$n.txt
  dd if=/tmp/noise_$n.txt of="$IMG_PATH" bs=1 seek="$noise_pos" conv=notrunc status=none
done

checksum=0
for ((c=0; c<${#PASSWORD}; c++)); do
  char="${PASSWORD:$c:1}"
  ascii=$(printf '%d' "'$char")
  checksum=$((checksum ^ ascii))
done
checksum=$((checksum ^ 0xFF))
echo "$checksum" > /app/checksum.txt

rm /app/launchcode.txt /app/secret.zip
rm -rf "$FRAG_DIR" /tmp/noise_*.txt
