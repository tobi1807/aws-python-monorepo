python_sources()

# The runtime is a single-file PEX (venv execution mode: unpacked once, fast
# start). `complete_platforms` is deliberately omitted: the image is built from
# python:3.13-slim, and the pex is packaged on the same interpreter family.
pex_binary(
    name="render",
    entry_point="render.py:main",
    execution_mode="venv",
)

# Pants builds this image (`pants package apps/invoicing/src/invoicing:image`),
# packaging the pex above first and exposing it to the Dockerfile as
# `apps.invoicing.src.invoicing/render.pex`.
# For CDK deploys the deploy tool does NOT use this target: it stages a plain
# Docker build context at dist/docker/invoicing (Dockerfile + render.pex) and
# CDK builds the image asset from it (see invoicing_infra/stack.py).
docker_image(
    name="image",
    source="Dockerfile",
    dependencies=[":render"],
    image_tags=["latest"],
)
