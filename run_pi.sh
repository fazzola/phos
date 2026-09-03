rsync -av --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  ./ pi@r192.168.1.128:/home/pi/phos/