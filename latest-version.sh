#!/bin/bash
# Prints the highest AMX Mod X release tag on GitHub, e.g. 1.10.0.5486
curl -fsSL 'https://api.github.com/repos/alliedmodders/amxmodx/releases?per_page=100' \
  | grep -oP '"tag_name":\s*"\K[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(?=")' \
  | sort -V | tail -1
