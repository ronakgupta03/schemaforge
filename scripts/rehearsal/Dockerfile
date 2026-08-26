# Rehearsal image: python + postgresql installed (validates sandbox_setup.sh
# script logic without re-downloading ~200MB of apt packages per iteration).
# Build:  docker build -f scripts/rehearsal/Dockerfile -t sf-rehearsal .
# Run:    docker run --rm -v $PWD:/workspace -w /workspace sf-rehearsal bash scripts/sandbox_setup.sh
FROM python:3.12-bookworm

RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-contrib \
    && rm -rf /var/lib/apt/lists/*