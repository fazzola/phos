rsync -av --delete \
  --exclude '__pycache__' \
  ./src/ pi@192.168.1.127:/home/pi/phos/src/

