#!/usr/bin/env python3
"""
Example strategy for Space Miners - Final Round (Upgrades).
This bot demonstrates upgrade management:
- Prioritizes collecting asteroids to gain score (which is used for upgrades)
- Upgrades ship parameters when ships return to base
- Balances between different upgrade types
- Makes strategic decisions about when to spend points on upgrades
"""

import json
import sys
import math

class UpgradeStrategy:
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

        print(f"Player {self.player_index} initialized with upgrade strategy", file=sys.stderr)

        # Signal readiness to the game runner
        print("READY", flush=True)

        # Energy thresholds
        self.CRITICAL_ENERGY = 20
        self.LOW_ENERGY = 40
        self.SAFE_ENERGY = 60

        # Upgrade priorities (will adapt based on ship role)
        self.upgrade_types = ["max_speed", "max_accel", "push_force", "energy_efficiency"]

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

    def is_in_base(self, ship_x, ship_y):
        """Check if ship is within base radius"""
        return self.distance(ship_x, ship_y, self.base_x, self.base_y) <= self.base_radius

    def calculate_upgrade_cost(self, current_level):
        """Calculate cost to upgrade from current level to next level"""
        return 5 * (current_level + 1)

    def choose_upgrade(self, ship, score, ship_role):
        """Choose which upgrade to purchase for a ship"""
        upgrades = ship.get("upgrades", {})
        
        # Get current levels (default to 0 if not present)
        max_speed_level = upgrades.get("max_speed", 0)
        max_accel_level = upgrades.get("max_accel", 0)
        push_force_level = upgrades.get("push_force", 0)
        energy_efficiency_level = upgrades.get("energy_efficiency", 0)

        # Define priorities based on ship role
        if ship_role == "collector":
            # Fast ships that collect asteroids
            priorities = [
                ("max_speed", max_speed_level),
                ("energy_efficiency", energy_efficiency_level),
                ("max_accel", max_accel_level),
                ("push_force", push_force_level),
            ]
        elif ship_role == "pusher":
            # Ships that push asteroids toward base
            priorities = [
                ("push_force", push_force_level),
                ("energy_efficiency", energy_efficiency_level),
                ("max_accel", max_accel_level),
                ("max_speed", max_speed_level),
            ]
        else:  # "balanced"
            # Balanced ships
            priorities = [
                ("energy_efficiency", energy_efficiency_level),
                ("max_accel", max_accel_level),
                ("max_speed", max_speed_level),
                ("push_force", push_force_level),
            ]

        # Try to upgrade the highest priority that we can afford
        for upgrade_name, current_level in priorities:
            cost = self.calculate_upgrade_cost(current_level)
            
            # Only upgrade if we can afford it and level isn't too high
            if score >= cost and current_level < 5:  # Cap at level 5 for this example
                print(f"Ship {ship['id']}: Upgrading {upgrade_name} from {current_level} to {current_level + 1} (cost: {cost})", file=sys.stderr)
                return upgrade_name

        return None  # No affordable upgrades

    def run(self):
        """Main game loop"""
        turn = 0
        
        # Assign roles to ships (could be dynamic based on game state)
        ship_roles = {
            0: "collector",   # Ship 0: Fast collector
            1: "pusher",      # Ship 1: Pusher specialist
            2: "balanced",    # Ship 2: Balanced
        }

        while True:
            # Read the current game state
            game_state = json.loads(input())
            turn = game_state.get("turn", turn)

            # Extract information
            my_ships = game_state["player"]["ships"]
            asteroids = game_state["asteroids"]
            score = game_state["player"].get("score", 0)

            print(f"Turn {turn}: Score = {score}", file=sys.stderr)

            # Prepare response with commands for each ship
            commands = []

            for ship in my_ships:
                ship_id = ship["id"]
                ship_x = ship["position"]["x"]
                ship_y = ship["position"]["y"]
                ship_vx = ship["velocity"]["x"]
                ship_vy = ship["velocity"]["y"]
                
                # Energy and upgrades are available in Final Round
                energy = ship.get("energy", 100)
                upgrades = ship.get("upgrades", {})

                # Calculate distance to base
                dist_to_base = self.distance(ship_x, ship_y, self.base_x, self.base_y)
                in_base = self.is_in_base(ship_x, ship_y)

                # Determine ship role
                ship_role = ship_roles.get(ship_id, "balanced")

                # Decide on upgrade
                upgrade = None
                if in_base and score >= 5 and turn < 300:  # Minimum cost is 5
                    upgrade = self.choose_upgrade(ship, score, ship_role)

                # Decide on movement
                acc_x, acc_y = 0, 0
                push = False

                # Energy management
                if energy < self.CRITICAL_ENERGY:
                    if in_base:
                        # Stay put to regenerate
                        acc_x = -ship_vx * 0.1
                        acc_y = -ship_vy * 0.1
                    else:
                        # Return to base
                        vec_x = self.base_x - ship_x
                        vec_y = self.base_y - ship_y
                        acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 1)

                elif energy < self.LOW_ENERGY and in_base:
                    # Regenerate a bit more
                    acc_x = -ship_vx * 0.2
                    acc_y = -ship_vy * 0.2

                else:
                    # Work based on role
                    if ship_role == "collector":
                        acc_x, acc_y, push = self.collector_behavior(
                            ship_x, ship_y, ship_vx, ship_vy, asteroids, energy
                        )
                    elif ship_role == "pusher":
                        acc_x, acc_y, push = self.pusher_behavior(
                            ship_x, ship_y, ship_vx, ship_vy, asteroids, energy
                        )
                    else:  # balanced
                        acc_x, acc_y, push = self.balanced_behavior(
                            ship_x, ship_y, ship_vx, ship_vy, asteroids, energy
                        )

                # Build command
                command = {
                    "ship_id": ship_id,
                    "acceleration": {
                        "x": acc_x,
                        "y": acc_y
                    },
                    "push": push
                }
                
                # Add upgrade if decided
                if upgrade:
                    command["upgrade"] = upgrade

                commands.append(command)

            # Send the commands
            action = {"commands": commands}
            print(json.dumps(action))

            # Flush stdout to ensure the game receives our response immediately
            sys.stdout.flush()

            turn += 1

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

    def find_valuable_asteroid(self, ship_x, ship_y, asteroids):
        """Find the most valuable nearby asteroid"""
        # Prioritize large asteroids that are relatively close
        best_asteroid = None
        best_score = -1

        size_values = {"large": 20, "medium": 10, "small": 5}

        for asteroid in asteroids:
            ast_x = asteroid["position"]["x"]
            ast_y = asteroid["position"]["y"]
            dist = self.distance(ship_x, ship_y, ast_x, ast_y)
            
            # Score = value / distance (prefer valuable and close asteroids)
            value = size_values.get(asteroid["size"], 5)
            score = value / (dist + 1)  # +1 to avoid division by zero

            if score > best_score:
                best_score = score
                best_asteroid = asteroid

        return best_asteroid

    def collector_behavior(self, ship_x, ship_y, ship_vx, ship_vy, asteroids, energy):
        """Behavior for collector ships: fast movement to asteroids"""
        asteroid = self.find_valuable_asteroid(ship_x, ship_y, asteroids)
        
        if asteroid is None:
            return 0, 0, False

        ast_x = asteroid["position"]["x"]
        ast_y = asteroid["position"]["y"]
        vec_x = ast_x - ship_x
        vec_y = ast_y - ship_y
        distance = math.sqrt(vec_x**2 + vec_y**2)

        # Use high acceleration to quickly reach asteroids
        acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 1.0)
        push = distance < 50 and energy > 30

        return acc_x, acc_y, push

    def pusher_behavior(self, ship_x, ship_y, ship_vx, ship_vy, asteroids, energy):
        """Behavior for pusher ships: push asteroids toward base"""
        asteroid = self.find_closest_asteroid(ship_x, ship_y, asteroids)
        
        if asteroid is None:
            return 0, 0, False

        ast_x = asteroid["position"]["x"]
        ast_y = asteroid["position"]["y"]
        distance = self.distance(ship_x, ship_y, ast_x, ast_y)

        if distance < 50:
            # Position to push toward base
            vec_x = self.base_x - ast_x
            vec_y = self.base_y - ast_y
            
            # Move to opposite side to push effectively
            target_x = ast_x - vec_x * 0.2
            target_y = ast_y - vec_y * 0.2
            
            acc_x = target_x - ship_x
            acc_y = target_y - ship_y
            acc_x, acc_y = self.normalize_vector(acc_x, acc_y, 0.7)
            push = True
        else:
            # Move toward asteroid
            vec_x = ast_x - ship_x
            vec_y = ast_y - ship_y
            acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 0.8)
            push = False

        return acc_x, acc_y, push

    def balanced_behavior(self, ship_x, ship_y, ship_vx, ship_vy, asteroids, energy):
        """Behavior for balanced ships: collect and push as needed"""
        asteroid = self.find_closest_asteroid(ship_x, ship_y, asteroids)
        
        if asteroid is None:
            return 0, 0, False

        ast_x = asteroid["position"]["x"]
        ast_y = asteroid["position"]["y"]
        vec_x = ast_x - ship_x
        vec_y = ast_y - ship_y
        distance = math.sqrt(vec_x**2 + vec_y**2)

        acc_x, acc_y = self.normalize_vector(vec_x, vec_y, 0.7)
        push = distance < 50 and energy > 20

        return acc_x, acc_y, push

if __name__ == "__main__":
    strategy = UpgradeStrategy()
    try:
        strategy.run()
    except Exception as e:
        # Log any errors to stderr for debugging
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
