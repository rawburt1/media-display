#!/bin/bash

rsync -av --delete --exclude __pycache__ --exclude config.yaml --exclude .venv /home/robert/src/media-display/vinyl_recognizer/ kodi-art:/home/robert/docker/vinyl_recognizer/
