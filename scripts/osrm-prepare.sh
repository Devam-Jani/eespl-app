#!/bin/sh
# Road distances for the travel claim: downloads the Geofabrik extract for western India (covers
# Gujarat) into data/osrm/ (gitignored, never committed) and prepares it for osrm-backend (MLD).
# Run once, and again when the map should be refreshed:
#   sh scripts/osrm-prepare.sh
# Then: docker compose up -d osrm
set -e
cd "$(dirname "$0")/.."
IMAGE=ghcr.io/project-osrm/osrm-backend:v5.27.1
URL=https://download.geofabrik.de/asia/india/western-zone-latest.osm.pbf
mkdir -p data/osrm
cd data/osrm
if [ ! -f western-zone-latest.osm.pbf ]; then
  echo "downloading $URL"
  curl -fL --retry 3 -o western-zone-latest.osm.pbf.part "$URL"
  mv western-zone-latest.osm.pbf.part western-zone-latest.osm.pbf
fi
ls -l western-zone-latest.osm.pbf
start=$(date +%s)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/data" $IMAGE osrm-extract -p /opt/car.lua /data/western-zone-latest.osm.pbf
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/data" $IMAGE osrm-partition /data/western-zone-latest.osrm
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/data" $IMAGE osrm-customize /data/western-zone-latest.osrm
echo "preprocessing took $(($(date +%s) - start)) seconds"
