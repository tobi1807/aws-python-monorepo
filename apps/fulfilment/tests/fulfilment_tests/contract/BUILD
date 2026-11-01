# Pact files are committed in pacts/ (file targets declared there). Pact paths
# are strings in test code, so dependency inference can't see them: declare them.
python_tests(
    name="tests",
    overrides={
        "test_order_placed_consumer.py": {"dependencies": ["pacts:fulfilment-orders"]},
        "test_order_fulfilled_provider.py": {"dependencies": ["pacts:notifications-fulfilment"]},
    },
)
