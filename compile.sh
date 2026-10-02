#!/bin/bash
exec python3 "$(dirname "$(readlink -f "$0")")/amxxci.py" compile "$@"
