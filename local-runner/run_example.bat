@echo off
python local_runner.py --game space_miners_hard --local "python examples/collector_strategy.py" "python examples/energy_management_strategy.py" %*
