#!/bin/sh
# Rebuild the page and push it. Run from cron once a day during the event.
set -e
cd /opt/data/profiles/belle/projects/whatshouldifly
python3 build.py
python3 scripts/ghpush.py GravityDeficient/whatshouldifly docs "daily rebuild: $(date -u +%Y-%m-%dT%H:%MZ)"
