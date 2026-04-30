#!/bin/bash
cd "$(dirname "$0")/backend"
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 5001 --reload
