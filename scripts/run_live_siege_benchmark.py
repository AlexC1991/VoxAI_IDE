import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.live_benchmark_runner import main


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)