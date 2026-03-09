#!/bin/bash
python3 local_runner.py --game space_miners_hard --local "python3 examples/collector_strategy.py" "python3 examples/energy_management_strategy.py" "$@"
