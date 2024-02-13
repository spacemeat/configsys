#!/bin/bash

repo_dir="./debian"

cd debian
PYTHONPATH="../linux" python3 -m config ./config.json

