FROM python:3.13-slim

# Pants puts the packaged pex in the build context under its target path.
# (When the deploy tool stages a context for CDK it provides the same layout.)
COPY apps.invoicing.src.invoicing/render.pex /app/render.pex

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/app/render.pex"]
