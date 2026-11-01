# Files read at synth time via Path(__file__).parent. Declared as resources so
# Pants packages them into the cdk_app PEX next to the Python modules.
resources(
    name="schema",
    sources=["schema.graphql"],
)

resources(
    name="resolvers",
    sources=["resolvers/*.vtl"],
)

python_sources(
    dependencies=[":schema", ":resolvers"],
)
