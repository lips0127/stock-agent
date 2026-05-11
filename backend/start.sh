#!/bin/bash
cd "$(dirname "$0")/.."
python -m backend.api.app
