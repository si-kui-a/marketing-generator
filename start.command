#!/bin/bash
cd "$(dirname "$0")"
open "http://localhost:8765/index.html"
python3 server.py
