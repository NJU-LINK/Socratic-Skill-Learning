#!/bin/bash
BASE_DIR=/app/varsea
mkdir -p "$BASE_DIR"

# populate /app/varsea with real looking files, dirs
for sub in tmp data logs backup cfg; do
  DIR="$BASE_DIR/$sub-$(head -c4 /dev/urandom | od -An -tx4 | tr -d ' ')"
  mkdir -p "$DIR"
  dd if=/dev/urandom of="$DIR/$(date +%s%N).bin" bs=512 count=10 status=none
  echo "Dummy entry at $(date +'%Y-%m-%d %H:%M:%S')" > "$DIR/$(date +%Y%m%d-%H%M%S).log"
done

# create config directory with hint
mkdir -p /app/config
cat > /app/config/app.conf << 'CONFEOF'
# Application Configuration File
# data_image points to the storage disk image used by the application
data_image = /app/varsea/storage/disk.dat
log_level = INFO
max_connections = 10
CONFEOF

# create decoy config files
for i in 1 2 3; do
  cat > "/app/config/service$i.conf" << CONFEOF
# Service $i Configuration
data_image = /app/varsea/storage/backup_$i.img
port = 80$i
CONFEOF
done

# create storage directory with decoy images
STORAGE_DIR=/app/varsea/storage
mkdir -p "$STORAGE_DIR"

# create decoy disk images with random data
for decoy in backup_1.img backup_2.img backup_3.img archive.dat; do
  dd if=/dev/urandom of="$STORAGE_DIR/$decoy" bs=1M count=4 status=none
done

# actual disk image path
IMG_PATH="$STORAGE_DIR/disk.dat"

# create a 4 MB disk image
dd if=/dev/urandom of="$IMG_PATH" bs=1M count=4 status=none

# write the password and zip it
PASSWORD="8XDA1B2C3D4E5F6G7H8W54"
echo "PASSWORD=$PASSWORD" > /app/launchcode.txt
zip /app/secret.zip /app/launchcode.txt > /dev/null

# find where password string starts in the zip
offset=$(strings -t d /app/secret.zip | grep PASSWORD= | awk '{print $1}')
split_point=$((offset + 20))

dd if=/app/secret.zip of=/app/secret.part.aa bs=1 count=$split_point status=none
dd if=/app/secret.zip of=/app/secret.part.ab bs=1 skip=$split_point status=none

# place fragment 1 at 1MB
FRAG1_SIZE=$(stat -c%s /app/secret.part.aa)
dd if=/app/secret.part.aa of="$IMG_PATH" bs=1 seek=$((1*1024*1024)) conv=notrunc status=none

# write noise overlapping with the last 3 bytes of fragment 1
# corrupts the tail of the password data inside the fragment
dd if=/dev/urandom of=/app/noise_block.bin bs=3 count=1 status=none
NOISE_OFFSET=$((1*1024*1024 + FRAG1_SIZE - 3))
dd if=/app/noise_block.bin of="$IMG_PATH" bs=1 seek=$NOISE_OFFSET conv=notrunc status=none

# place fragment 2 at 3MB
dd if=/app/secret.part.ab of="$IMG_PATH" bs=1 seek=$((3*1024*1024)) conv=notrunc status=none

# place decoy noise at 2MB to match seed pattern
echo "system check ok INFO: system check ok" > /app/logs.txt
dd if=/app/logs.txt of="$IMG_PATH" bs=1M seek=2 conv=notrunc status=none

rm -f /app/launchcode.txt /app/secret.zip /app/secret.part.* /app/logs.txt /app/noise_block.bin
