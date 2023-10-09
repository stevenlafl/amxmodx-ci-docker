#!/bin/bash

mkdir -p compiled

if [ $# -eq 0 ]; then
  for f in *.sma; do
    echo "Compiling $f ..."
    amxxpc -i/amxmodx/include -iinclude "$f"
    echo ""
  done;

  mv *.amxx compiled/
  exit 0
fi

amxxpc -i/amxmodx/include -iinclude "$@"
mv *.amxx compiled/