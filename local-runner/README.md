# Local Game Runner

This is a simplified script for running games locally to develop and test your strategies without needing to submit them to the competition platform.

## Key Features

- **No timeout enforcement**: Unlike the competition environment, the local runner allows your strategies unlimited thinking time per turn, making it perfect for development and debugging.
- **Customizable game settings**: Adjust game-specific parameters.
- **Replay system**: Save and debug games against previous runs.
- **Easy testing**: Run multiple strategies against each other locally.

## Getting Started

### Requirements
- Python 3.6 or higher
- Game-specific dependencies.

### Running a Simple Game

The easiest way to get started is to run the example script:

```bash
./run_example.sh
```

This will run a game between the included example strategies. To run other games, you will need to use the `local_runner.py` script directly.

### Creating Your Own Strategy

1. Study the example strategies in the `examples` directory to understand how to implement your own.
2. Create a new Python file for your strategy. It should:
   - Read the initial game info on startup
   - Enter a loop that reads game state and outputs commands for each turn
   - Handle JSON input/output correctly

The exact input/output format is provided in the game rules.

### Minimal Multi-Language Strategy Examples

The `test-strategies/` directory contains minimal "do-nothing" starter strategies for all supported languages except C:

| File | Language |
|---|---|
| `main.java` | Java |
| `main.scala` | Scala |
| `main.kt` | Kotlin |
| `main.py` | Python |
| `main.js` | JavaScript (Node.js) |
| `main.go` | Go |
| `main.cs` | C# |
| `main.rs` | Rust |
| `main.cpp` | C++ |
| `main.swift` | Swift |

Each file correctly handles the startup handshake (reads the initial config line and prints `READY`), then loops reading game state and responding with zero-acceleration commands for every ship. They do nothing strategically — but they compile, run, and communicate correctly with the game engine, making them ideal starting templates.

### Command Line Options

Run a local game with your strategies:

```bash
python local_runner.py --local "python path/to/strategy1.py" "./path/to/strategy2"
```

Save a replay for later analysis:

```bash
python local_runner.py --local "python s1.py" "python s2.py" --save-replay my_game.replay
```

Debug your strategy against a saved replay:

```bash
python local_runner.py --replay my_game.replay --strategy my_strategy.py --player 0
```

Stop replay at a specific tick (inclusive):

```bash
python local_runner.py --replay my_game.replay --strategy "./my_bot" --player 0 --last-tick 250
```

## Game-Specific Documentation

The format for game state, initial information, and strategy commands is specific to each game. Please refer to the documentation inside the `games/<game_name>/` directory for details on the game you are playing.

## Development vs Competition Environment

**Important**: The local runner provides a **development-friendly environment** that differs from the competition:

### Timeout Behavior
- **Local Runner**: No time limits per turn - your strategy can think as long as needed.
- **Competition**: Strict timeouts of 0.05 seconds per turn (0.25 seconds for the first turn).

### Recommendations
1. **During Development**: Use the local runner to develop and debug your logic without time pressure.
2. **Before Submission**: Test your strategy's performance to ensure it can execute within competition time limits.
3. **Optimization**: Once your strategy works locally, optimize it for speed to meet competition constraints.

### Performance Testing
You can test timeout behavior by running strategies that include timing measurements:
```python
import time
start = time.time()
# Your strategy logic here
duration = time.time() - start
print(f"Turn took {duration:.3f} seconds", file=sys.stderr)
```
