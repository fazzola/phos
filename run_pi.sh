#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"

# Copy only release source/docs/scripts/metadata; preserve Pi settings and credentials.
ssh pi@192.168.1.127 'mkdir -p /home/pi/phos/src /home/pi/phos/config /home/pi/phos/docs /home/pi/phos/deploy /home/pi/phos/scripts'
rsync -av --delete --exclude '__pycache__' ./src/ pi@192.168.1.127:/home/pi/phos/src/
rsync -av --delete --exclude '__pycache__' ./scripts/ pi@192.168.1.127:/home/pi/phos/scripts/
rsync -av ./pyproject.toml ./requirements-web.txt ./requirements.txt ./README.md pi@192.168.1.127:/home/pi/phos/
rsync -av ./deploy/ pi@192.168.1.127:/home/pi/phos/deploy/
rsync -av ./docs/ pi@192.168.1.127:/home/pi/phos/docs/
rsync -av --ignore-existing ./config/phos.json pi@192.168.1.127:/home/pi/phos/config/
