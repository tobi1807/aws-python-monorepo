# features.json is read at synth time and published as the AppConfig hosted
# configuration, so it must travel with the code (PEX, tests).
resource(
    name="features",
    source="flags/features.json",
)

python_sources(
    dependencies=[":features"],
)
