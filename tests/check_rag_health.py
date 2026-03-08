import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

TEST_MODULES = [
    "tests.test_rag_agent_flow",
    "tests.test_rag_client",
    "tests.test_rag_tools",
]


def main() -> int:
    print(f"Running RAG healthcheck from project root: {PROJECT_ROOT}")
    print("Included test modules:")
    for name in TEST_MODULES:
        print(f" - {name}")

    suite = unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("--- RAG Healthcheck Passed ---")
        return 0

    print("--- RAG Healthcheck Failed ---")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

