VERSION=$(./latest-version.sh)
docker build --build-arg VERSION=$VERSION -t stevenlafl/amxmodx-ci:$VERSION -t stevenlafl/amxmodx-ci .
