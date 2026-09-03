rsync -av --delete \
  --exclude '__pycache__' \
  ./src/ pi@192.168.1.128:/home/pi/phos/src/
