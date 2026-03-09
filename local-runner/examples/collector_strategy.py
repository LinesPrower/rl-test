#!/usr/bin/env python3
"""
Example strategy for Space Miners competition.
This bot implements a basic "collect and return" behavior.
"""

import json
import sys
import math
import random

class CollectorStrategy:
    def __init__(self):
        # Read the initial game info
        self.init_data = json.loads(input())
        self.player_index = self.init_data["player_index"]
        self.width = self.init_data["width"]
        self.height = self.init_data["height"]

        # Determine our base position (left or right side)
        self.base_x = 0 if self.player_index == 0 else self.width
        self.base_y = self.height / 2

        print(f"I am player {self.player_index} with base at ({self.base_x}, {self.base_y})", file=sys.stderr)

        # Signal readiness to the game runner
        print("READY", flush=True)

        # Ship states - keeps track of what each ship is doing
        self.ship_states = {}

    def distance(self, x1, y1, x2, y2):
        """Calculate Euclidean distance between two points"""
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    def normalize_vector(self, x, y, desired_magnitude=1.0):
        """Normalize a vector to the desired magnitude"""
        current_magnitude = math.sqrt(x**2 + y**2)
        if current_magnitude == 0:
            return 0, 0

        ratio = desired_magnitude / current_magnitude
        return x * ratio, y * ratio

    def run(self):
        """Main game loop"""
        while True:
            # Read the current game state
            game_state = json.loads(input())

            # Extract information about our ships and asteroids
            my_ships = game_state["player"]["ships"]
            asteroids = game_state["asteroids"]

            # Prepare response with commands for each ship
            commands = []

            for ship in my_ships:
                ship_id = ship["id"]
                ship_x = ship["position"]["x"]
                ship_y = ship["position"]["y"]
                ship_vx = ship["velocity"]["x"]
                ship_vy = ship["velocity"]["y"]

                # Initialize state for new ships
                if ship_id not in self.ship_states:
                    self.ship_states[ship_id] = "SEEKING"

                # Get current state
                state = self.ship_states[ship_id]

                # Distance to base
                dist_to_base = self.distance(ship_x, ship_y, self.base_x, self.base_y)

                # Decision making based on state
                if state == "SEEKING":
                    # Look for the closest asteroid
                    closest_asteroid = None
                    min_distance = float('inf')

                    for asteroid in asteroids:
                        ast_x = asteroid["position"]["x"]
                        ast_y = asteroid["position"]["y"]
                        dist = self.distance(ship_x, ship_y, ast_x, ast_y)

                        if dist < min_distance:
                            min_distance = dist
                            closest_asteroid = asteroid

                    # If no asteroids, just stay put
                    if closest_asteroid is None:
                        acc_x, acc_y = 0, 0
                        push = False
                    else:
                        # Head toward the asteroid
                        ast_x = closest_asteroid["position"]["x"]
                        ast_y = closest_asteroid["position"]["y"]

                        # Vector to asteroid
                        vec_x = ast_x - ship_x
                        vec_y = ast_y - ship_y

                        # Normalize to get direction with max acceleration
                        acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 1.0)

                        # If close to asteroid, push it toward our base
                        if min_distance < 50:  # Push range
                            self.ship_states[ship_id] = "PUSHING"
                            push = True
                        else:
                            push = False

                elif state == "PUSHING":
                    # Find the closest asteroid again
                    closest_asteroid = None
                    min_distance = float('inf')

                    for asteroid in asteroids:
                        ast_x = asteroid["position"]["x"]
                        ast_y = asteroid["position"]["y"]
                        dist = self.distance(ship_x, ship_y, ast_x, ast_y)

                        if dist < min_distance:
                            min_distance = dist
                            closest_asteroid = asteroid

                    # If no asteroids or too far, go back to seeking
                    if closest_asteroid is None or min_distance > 50:
                        self.ship_states[ship_id] = "SEEKING"
                        acc_x, acc_y = 0, 0
                        push = False
                    else:
                        # Vector from asteroid to base
                        ast_x = closest_asteroid["position"]["x"]
                        ast_y = closest_asteroid["position"]["y"]

                        # If we successfully pushed the asteroid close to base, go back to seeking
                        dist_ast_to_base = self.distance(ast_x, ast_y, self.base_x, self.base_y)
                        if dist_ast_to_base < 100:
                            self.ship_states[ship_id] = "SEEKING"

                        # Push toward base
                        vec_x = self.base_x - ast_x
                        vec_y = self.base_y - ast_y

                        # Position ourselves to push in the right direction
                        target_x = ast_x - vec_x * 0.1  # Slightly behind the asteroid
                        target_y = ast_y - vec_y * 0.1

                        # Accelerate toward that position
                        acc_x = target_x - ship_x
                        acc_y = target_y - ship_y
                        acc_x, acc_y = self.normalize_vector(acc_x, acc_y, 1.0)

                        push = True  # Always push when in PUSHING state

                # Add command for this ship
                commands.append({
                    "ship_id": ship_id,
                    "acceleration": {
                        "x": acc_x,
                        "y": acc_y
                    },
                    "push": push
                })

            # Send the commands
            action = {"commands": commands}
            print(json.dumps(action))

            # Flush stdout to ensure the game receives our response immediately
            sys.stdout.flush()

if __name__ == "__main__":
    strategy = CollectorStrategy()
    try:
        strategy.run()
    except Exception as e:
        # Log any errors to stderr for debugging
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
