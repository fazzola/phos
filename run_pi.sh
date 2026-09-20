rsync -av --delete \
  --exclude '__pycache__' \
  ./src/ pi@192.168.1.127:/home/pi/phos/src/

# Seed the canonical configuration once; preserve settings edited on the Pi.
# Create /home/pi/phos/config on first setup (see docs/installation.md).
rsync -av --ignore-existing \
  ./config/phos.json pi@192.168.1.127:/home/pi/phos/config/
