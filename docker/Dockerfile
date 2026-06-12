# The dos-kernel container (issue #55) — the verdicts without a Python toolchain.
#
#   docker run --rm -v "$PWD:/work" ghcr.io/anthony-chaudhary/dos-kernel \
#     dos doctor --workspace /work
#
# Built from the repo tree at the checked-out ref (the publish workflow builds
# at tag time, so the image version always equals the tag — no PyPI lag).

FROM python:3.12-slim

# git is not optional: every truth verdict reads git ancestry. And a mounted
# /work is owned by the HOST uid, which git refuses by default ("dubious
# ownership") — a single-purpose container trusts its mounts, so widen it
# here or the headline `-v $PWD:/work` use breaks on most hosts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system safe.directory '*'

COPY . /src
RUN pip install --no-cache-dir "/src[mcp]"

# The kernel adjudicates the workspace MOUNTED at /work, never its own image.
WORKDIR /work

# No ENTRYPOINT, so `docker run IMAGE dos verify …` reads as written. The
# default command is the MCP server on stdio — what a registry's introspection
# check (and an MCP client launching servers as containers) starts.
CMD ["dos-mcp"]
