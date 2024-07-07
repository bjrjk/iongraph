#!/bin/bash
python2 ghetto-iongraph.py --js-path obj-debug-x86_64-pc-linux-gnu/dist/bin/js --script-path PoC.js --overwrite
cd iongraph-out
python3 -m http.server