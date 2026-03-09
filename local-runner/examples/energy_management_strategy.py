#!/usr/bin/env python3
"""
Example strategy for Space Miners - Round 2 (Energy Management).
This bot demonstrates energy-aware behavior:
- Ships return to base when energy is low to regenerate
- Ships stay in base if energy is critically low
- Ships avoid expensive actions when energy is insufficient
"""

import json
import sys
import math

class EnergyManagementStrategy:
    def __init__(self):
        # Read the initial game info
        self.init_data = json.loads(input())
        self.player_index = self.init_data["player_index"]
        self.width = self.init_data["width"]
        self.height = self.init_data["height"]

        # Determine our base position (left or right side)
        self.base_x = 0 if self.player_index == 0 else self.width
        self.base_y = self.height / 2
        self.base_radius = 100  # Base collection/regeneration radius

        print(f"Player {self.player_index} initialized with energy management", file=sys.stderr)

        # Signal readiness to the game runner
        print("READY", flush=True)

        # Energy thresholds
        self.CRITICAL_ENERGY = 20  # Stay in base below this
        self.LOW_ENERGY = 40       # Return to base below this
        self.SAFE_ENERGY = 60      # Can leave base above this

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

    def estimate_energy_cost(self, acc_magnitude, use_push):
        """Estimate energy cost for actions"""
        accel_cost = 0.5 * (acc_magnitude ** 1.2) if acc_magnitude > 0 else 0
        push_cost = 0.5 if use_push else 0
        return accel_cost + push_cost

    def is_in_base(self, ship_x, ship_y):
        """Check if ship is within base radius"""
        return self.distance(ship_x, ship_y, self.base_x, self.base_y) <= self.base_radius

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
                
                # Energy field is available in Round 2
                energy = ship.get("energy", 100)  # Default to 100 if not present

                # Calculate distance to base
                dist_to_base = self.distance(ship_x, ship_y, self.base_x, self.base_y)
                in_base = self.is_in_base(ship_x, ship_y)

                acc_x, acc_y = 0, 0
                push = False

                # Critical energy: Stay in base and regenerate
                if energy < self.CRITICAL_ENERGY:
                    if in_base:
                        # Stay put to regenerate
                        # Apply small damping to velocity to stay near base center
                        acc_x = -ship_vx * 0.1
                        acc_y = -ship_vy * 0.1
                        push = False
                        print(f"Ship {ship_id}: Critical energy ({energy:.1f}), staying in base", file=sys.stderr)
                    else:
                        # Emergency return to base
                        vec_x = self.base_x - ship_x
                        vec_y = self.base_y - ship_y
                        # Use minimal acceleration to conserve energy
                        acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 0.3)
                        push = False
                        print(f"Ship {ship_id}: Critical energy ({energy:.1f}), emergency return", file=sys.stderr)

                # Low energy: Return to base
                elif energy < self.LOW_ENERGY:
                    if in_base and energy < self.SAFE_ENERGY:
                        # Stay and regenerate until safe level
                        acc_x = -ship_vx * 0.2
                        acc_y = -ship_vy * 0.2
                        push = False
                        print(f"Ship {ship_id}: Low energy ({energy:.1f}), regenerating in base", file=sys.stderr)
                    elif not in_base:
                        # Head back to base
                        vec_x = self.base_x - ship_x
                        vec_y = self.base_y - ship_y
                        acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 0.5)
                        push = False
                        print(f"Ship {ship_id}: Low energy ({energy:.1f}), returning to base", file=sys.stderr)
                    else:
                        # Energy recovering, can start working
                        closest_asteroid = self.find_closest_asteroid(ship_x, ship_y, asteroids)
                        if closest_asteroid:
                            acc_x, acc_y, push = self.pursue_asteroid(
                                ship_x, ship_y, closest_asteroid, energy, conservative=True
                            )

                # Good energy: Work normally
                else:
                    closest_asteroid = self.find_closest_asteroid(ship_x, ship_y, asteroids)
                    
                    if closest_asteroid is None:
                        # No asteroids, stay near base
                        if dist_to_base > self.base_radius:
                            vec_x = self.base_x - ship_x
                            vec_y = self.base_y - ship_y
                            acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 0.3)
                    else:
                        acc_x, acc_y, push = self.pursue_asteroid(
                            ship_x, ship_y, closest_asteroid, energy, conservative=False
                        )

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

    def find_closest_asteroid(self, ship_x, ship_y, asteroids):
        """Find the closest asteroid to the ship"""
        closest_asteroid = None
        min_distance = float('inf')

        for asteroid in asteroids:
            ast_x = asteroid["position"]["x"]
            ast_y = asteroid["position"]["y"]
            dist = self.distance(ship_x, ship_y, ast_x, ast_y)

            if dist < min_distance:
                min_distance = dist
                closest_asteroid = asteroid

        return closest_asteroid

    def pursue_asteroid(self, ship_x, ship_y, asteroid, energy, conservative=False):
        """Calculate acceleration and push for pursuing an asteroid"""
        ast_x = asteroid["position"]["x"]
        ast_y = asteroid["position"]["y"]

        # Vector to asteroid
        vec_x = ast_x - ship_x
        vec_y = ast_y - ship_y
        distance = math.sqrt(vec_x**2 + vec_y**2)

        # Decide on push
        push = distance < 50  # Within push range

        # Adjust acceleration based on energy and mode
        if conservative:
            # Use less acceleration when energy is recovering
            desired_accel = 0.5
        else:
            # Use more acceleration when energy is good
            desired_accel = 1.0

        # Estimate cost
        estimated_cost = self.estimate_energy_cost(desired_accel, push)
        
        # If we can't afford the action, reduce it
        if estimated_cost > energy:
            if push and energy < 0.5:
                push = False  # Disable push if we can't afford it
            desired_accel = min(desired_accel, 0.2)  # Use minimal acceleration

        # Calculate acceleration
        acc_x, acc_y = self.normalize_vector(vec_x, vec_y, desired_accel)

        return acc_x, acc_y, push

if __name__ == "__main__":
    strategy = EnergyManagementStrategy()
    try:
        strategy.run()
    except Exception as e:
        # Log any errors to stderr for debugging
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
