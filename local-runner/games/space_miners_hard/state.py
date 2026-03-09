import random
import math
import json
import logging
from typing import List, Dict, Any
import Box2D
from Box2D import b2World, b2Vec2, b2BodyDef, b2FixtureDef, b2PolygonShape, b2_dynamicBody, b2CircleShape

from base_game_state import BaseGameState

# Game world constants
GAME_WIDTH = 1280
GAME_HEIGHT = 800

# Physics constants
MAX_ACCELERATION = 5.0
MAX_VELOCITY = 15
PPM = 10  # Pixels Per Meter (10 game units = 1 meter)
DT = 0.1  # Seconds per physics step
ACC_SCALE = (1/PPM) / (DT**2)  # Converts game units/turn² to m/s²
PUSH_RADIUS_UNITS = 50
PUSH_FORCE_MAX = 2000.0  # Max push force in game units
BASE_COLLECTION_RADIUS_UNITS = 100

# Ship and asteroid physical properties
SHIP_RADIUS_UNITS = 15
SHIP_MASS = 10
ASTEROID_RADIUS_UNITS = {'small': 5, 'medium': 10, 'large': 20}
ASTEROID_MASS = {'small': 15, 'medium': 20, 'large': 30}

CATEGORY_SHIP = 0x0002
CATEGORY_ASTEROID = 0x0004
CATEGORY_WALL = 0x0001

# Preset configurations - Game-specific rules for each competition round
# The platform passes preset names, and the game runner knows what they mean
PRESET_CONFIGS = {
    "Round 1": {
        "ship_count": 3,
        "energy_enabled": False,
        "upgrades_enabled": False
    },
    "Round 2": {
        "ship_count": 3,
        "energy_enabled": True,
        "upgrades_enabled": False
    },
    "Final Round": {
        "ship_count": 3,
        "energy_enabled": True,
        "upgrades_enabled": True
    }
}

# Helper function to calculate density based on mass and radius
def _density(mass, radius_units):
    return mass / (math.pi * (radius_units/PPM)**2)

class Ship:
    def __init__(self, id: int, body: Box2D.b2Body = None):
        self.id = id
        self.body = body
        self.position = b2Vec2(0, 0)
        self.velocity = b2Vec2(0, 0)
        self.energy = 100.0  # Maximum energy
        self.upgrades = {
            'max_speed': 0,
            'max_accel': 0,
            'push_force': 0,
            'energy_efficiency': 0
        }

    def get_acceleration_cost(self, acceleration_magnitude: float) -> float:
        """Calculate energy cost for acceleration based on formula: 0.25 * max(0, |a|-1)^1.25"""
        base_cost = 0.25 * (max(0, acceleration_magnitude - 1) ** 1.25)
        # Apply energy efficiency upgrade
        efficiency_level = self.upgrades['energy_efficiency']
        return base_cost / (1 + efficiency_level * 0.10)

    def get_push_cost(self) -> float:
        """Calculate energy cost for push action"""
        return 0.25

    def get_effective_max_speed(self) -> float:
        """Calculate effective max speed based on upgrades and energy"""
        base_speed = 15 * (1 + self.upgrades['max_speed'] * 0.10)
        energy_factor = 0.2 + 0.8 * (self.energy / 100.0)
        return base_speed * energy_factor

    def get_effective_max_acceleration(self) -> float:
        """Calculate effective max acceleration based on upgrades and energy"""
        base_accel = 5 * (1 + self.upgrades['max_accel'] * 0.10)
        energy_factor = 0.2 + 0.8 * (self.energy / 100.0)
        return base_accel * energy_factor

    def get_effective_push_force(self) -> float:
        """Calculate effective push force based on upgrades"""
        return PUSH_FORCE_MAX * (1 + self.upgrades['push_force'] * 0.10)

    def regenerate_energy(self):
        """Regenerate 4 energy units if at base"""
        self.energy = min(100.0, self.energy + 4.0)

    def consume_energy(self, amount: float):
        """Consume energy, ensuring it doesn't go below 0"""
        self.energy = max(0.0, self.energy - amount)

    def to_dict(self, include_energy=False, include_upgrades=False):
        if self.body:
            pos = self.body.position
            vel = self.body.linearVelocity
        else:
            pos = self.position
            vel = self.velocity
        result = {
            'id': self.id,
            'position': {'x': pos.x * PPM, 'y': pos.y * PPM},
            'velocity': {'x': vel.x * PPM * DT, 'y': vel.y * PPM * DT}
        }
        if include_energy:
            result['energy'] = self.energy
        if include_upgrades:
            result['upgrades'] = self.upgrades.copy()
        return result

    def update_from_dict(self, data: Dict):
        self.position = b2Vec2(data['position']['x'] / PPM, data['position']['y'] / PPM)
        self.velocity = b2Vec2(data['velocity']['x'] / PPM / DT, data['velocity']['y'] / PPM / DT)
        if 'energy' in data:
            self.energy = data['energy']
        if 'upgrades' in data:
            self.upgrades = data['upgrades'].copy()

class Asteroid:
    def __init__(self, id: int, body: Box2D.b2Body = None, size: str = None):
        self.id = id
        self.body = body
        self.size = size
        self.position = b2Vec2(0, 0)
        self.velocity = b2Vec2(0, 0)

    def to_dict(self):
        if self.body:
            pos = self.body.position
            vel = self.body.linearVelocity
        else:
            pos = self.position
            vel = self.velocity
        return {
            'id': self.id,
            'position': {'x': pos.x * PPM, 'y': pos.y * PPM},
            'velocity': {'x': vel.x * PPM * DT, 'y': vel.y * PPM * DT},
            'size': self.size
        }

    def update_from_dict(self, data: Dict):
        self.position = b2Vec2(data['position']['x'] / PPM, data['position']['y'] / PPM)
        self.velocity = b2Vec2(data['velocity']['x'] / PPM / DT, data['velocity']['y'] / PPM / DT)
        self.size = data['size']

class Player:
    def __init__(self, id: int, base_x: float):
        self.id = id
        self.score = 0
        self.ships: List[Ship] = []
        self.base_x = base_x
        self.is_active = True
        self.disqualification_reason = None
        self.last_score_change_tick = 0  # Track when score last changed

    def spend_score(self, amount: int) -> bool:
        """Spend score points - tie-breaker tick updated by GameState when processing upgrades"""
        if self.score >= amount:
            self.score -= amount
            return True
        return False

    def to_dict(self, include_energy=False, include_upgrades=False):
        res = {
            'score': self.score,
            'ships': [ship.to_dict(include_energy, include_upgrades) for ship in self.ships],
            'last_score_change_tick': self.last_score_change_tick
        }
        if not self.is_active:
            res['failed'] = self.disqualification_reason
        return res

    def update_from_dict(self, data: Dict):
        self.score = data['score']
        if 'last_score_change_tick' in data:
            self.last_score_change_tick = data['last_score_change_tick']
        if 'failed' in data:
            self.is_active = False
            self.disqualification_reason = data['failed']
        else:
            self.is_active = True

        for ship_data in data['ships']:
            ship = next((s for s in self.ships if s.id == ship_data['id']), None)
            if ship:
                ship.update_from_dict(ship_data)
            else:
                new_ship = Ship(ship_data['id'])
                new_ship.update_from_dict(ship_data)
                self.ships.append(new_ship)

class SpaceMinersHardGameState(BaseGameState):
    def __init__(self, game_options: Dict[str, Any] = None, logger: logging.Logger = None):
        # Copy options so callers can't mutate them during play
        opts = dict(game_options or {})
        super().__init__(opts, logger)

        if self.logger is None:
            self.logger = logging.getLogger(__name__)

        # Determine game parameters based on preset first
        preset = None
        if not self.game_options.get('is_replay', False):
            preset = self.game_options.get('preset', 'Round 1')
        
        # Set energy and upgrades based on preset or explicit options
        if preset:
            # Preset games: use preset configuration for energy and upgrades
            preset_config = PRESET_CONFIGS.get(preset, PRESET_CONFIGS["Round 1"])
            self.energy_enabled = preset_config.get('energy_enabled', False)
            self.upgrades_enabled = preset_config.get('upgrades_enabled', False)
            self.logger.info(f"Preset '{preset}': energy={self.energy_enabled}, upgrades={self.upgrades_enabled}")
        else:
            # Replays: use explicit options (or defaults for backwards compatibility)
            self.energy_enabled = self.game_options.get('energy_enabled', True)
            self.upgrades_enabled = self.game_options.get('upgrades_enabled', True)
        
        self.round = self.game_options.get('round', 'Final Round' if self.upgrades_enabled else 'Round 2' if self.energy_enabled else 'Round 1')

        # Width and height are constants defined at module level
        self.width = GAME_WIDTH / PPM
        self.height = GAME_HEIGHT / PPM
        self.world = None
        self.players = [
            Player(0, 0),
            Player(1, self.width * PPM)
        ]
        self.asteroids: List[Asteroid] = []
        self._next_asteroid_id = 0  # Monotonically increasing counter to avoid duplicate IDs
        self.initial_asteroids = 8  # Default, will be set properly below

        if not self.game_options.get('is_replay', False):
            preset_config = PRESET_CONFIGS.get(preset, PRESET_CONFIGS["Round 1"])
            ship_count = preset_config['ship_count']
            self.initial_asteroids = random.randint(3, 20)
            self.logger.info(f"Using preset '{preset}': {ship_count} ships, {self.initial_asteroids} asteroids")
            
            self.world = b2World(gravity=(0, 0))
            self.create_walls()
            self.initialize_ships(ship_count)

            while len(self.asteroids) + 1 < self.initial_asteroids:
                self.spawn_asteroid_pair()

            if len(self.asteroids) + 1 == self.initial_asteroids:
                self.spawn_asteroid_middle()

    def create_walls(self):
        # Define the ground body.
        ground_body_def = b2BodyDef()
        ground_body_def.position = (0, 0)

        # Call the body factory which allocates memory for the ground body
        # from a pool and creates the ground box shape (also from a pool).
        ground = self.world.CreateBody(ground_body_def)

        # Define the ground box shape.
        ground_box = b2PolygonShape()
        wall_fixture_def = b2FixtureDef(
            shape=ground_box,
            density=0.0,
            restitution=0.5,
            categoryBits=CATEGORY_WALL,  # This fixture is in the WALL category
            maskBits=CATEGORY_SHIP | CATEGORY_ASTEROID  # It collides with ships and asteroids
        )

        # Bottom (center is shifted down by half-height to place it outside)
        ground_box.SetAsBox(self.width / 2, 1, b2Vec2(self.width / 2, -1), 0)
        ground.CreateFixture(wall_fixture_def)

        # Top (center is shifted up by half-height)
        ground_box.SetAsBox(self.width / 2, 1, b2Vec2(self.width / 2, self.height + 1), 0)
        ground.CreateFixture(wall_fixture_def)

        # Left (center is shifted left by half-width)
        ground_box.SetAsBox(1, self.height / 2, b2Vec2(-1, self.height / 2), 0)
        ground.CreateFixture(wall_fixture_def)

        # Right (center is shifted right by half-width)
        ground_box.SetAsBox(1, self.height / 2, b2Vec2(self.width + 1, self.height / 2), 0)
        ground.CreateFixture(wall_fixture_def)

    def initialize_ships(self, ship_count):
        angle_step = math.pi / (ship_count + 1)
        for player in self.players:
            for i in range(ship_count):
                body_def = b2BodyDef()
                body_def.type = b2_dynamicBody
                body_def.bullet = True
                body_def.fixedRotation = True
                dx = self.width / 2 - player.base_x
                angle = math.pi / 2 - dx / abs(dx) * (i + 1) * angle_step
                shift_x = math.cos(angle) * BASE_COLLECTION_RADIUS_UNITS
                shift_y = math.sin(angle) * BASE_COLLECTION_RADIUS_UNITS
                body_def.position = (player.base_x / PPM + shift_x / PPM, self.height / 2 + shift_y / PPM)
                body = self.world.CreateBody(body_def)

                radius = SHIP_RADIUS_UNITS / PPM
                shape = b2CircleShape(radius=radius)

                fixture_def = b2FixtureDef(
                    shape=shape,
                    density=_density(SHIP_MASS, SHIP_RADIUS_UNITS),
                    friction=0.0,
                    restitution=0.5,
                    categoryBits=CATEGORY_SHIP,  # This fixture is in the SHIP category
                    maskBits=CATEGORY_SHIP | CATEGORY_ASTEROID | CATEGORY_WALL  # It collides with ships, asteroids, and walls
                )
                body.CreateFixture(fixture_def)
                body.userData = {'type': 'ship', 'player_id': player.id}
                ship = Ship(i, body)
                player.ships.append(ship)

    def update(self, actions: List[Dict[int, Dict]]):
        self.tick += 1
        self.logger.debug(f"Update tick {self.tick}, actions: {json.dumps(actions)}")

        # 1. Start of Turn: Determine each ship's effective performance based on current energy
        # 2. Process Commands: Read commands and cap acceleration by scaling the vector if needed
        energy_costs = {}  # Track energy costs for each ship

        for i, player in enumerate(self.players):
            if not player.is_active or actions[i] is None:
                continue

            player_actions = actions[i]
            commands = player_actions["commands"]
            energy_costs[i] = {}

            for action in commands:
                ship_id = action["ship_id"]
                ship = player.ships[ship_id]
                
                # --- Start of atomic energy system ---

                # 1. Calculate the total potential cost of all actions for this ship
                total_cost = 0.0
                acceleration = b2Vec2(action['acceleration']['x'], action['acceleration']['y'])
                accel_magnitude = acceleration.length
                
                # Cap acceleration magnitude based on effective max acceleration
                if self.energy_enabled:
                    max_accel = ship.get_effective_max_acceleration()
                else:
                    max_accel = MAX_ACCELERATION

                if accel_magnitude > max_accel:
                    self.logger.debug(f"Capping acceleration magnitude from {accel_magnitude} to {max_accel}")
                    acceleration.Normalize()
                    acceleration *= max_accel
                    accel_magnitude = max_accel

                if self.energy_enabled:
                    if accel_magnitude > 0:
                        total_cost += ship.get_acceleration_cost(accel_magnitude)
                    if action['push']:
                        total_cost += ship.get_push_cost()

                # 2. Check if the ship has enough energy before acting
                if not self.energy_enabled or ship.energy >= total_cost:
                    # 3. If it does, apply forces and set the cost to be deducted later
                    energy_costs[i][ship_id] = total_cost

                    # Apply acceleration force
                    a_world = acceleration * ACC_SCALE
                    ship.body.ApplyForceToCenter(a_world * ship.body.mass, True)

                    # Apply push force
                    if action['push']:
                        if self.energy_enabled:
                            push_force = ship.get_effective_push_force()
                            self.apply_push(ship, push_force)
                        else:
                            self.apply_push(ship)
                else:
                    # If not enough energy, do nothing and incur no cost
                    energy_costs[i][ship_id] = 0.0
                    self.logger.debug(f"Player {i} ship {ship_id} insufficient energy: needs {total_cost:.2f}, has {ship.energy:.2f}")

                # --- End of atomic energy system ---

        # 3. Apply Physics: Update all object positions and velocities
        self.world.Step(DT, 10, 10)

        # Cap velocities based on effective max speed
        for body in self.world.bodies:
            if body.userData and body.userData['type'] == 'ship':
                player_id = body.userData['player_id']
                ship = None
                for s in self.players[player_id].ships:
                    if s.body == body:
                        ship = s
                        break

                if ship and self.energy_enabled:
                    max_speed = ship.get_effective_max_speed()
                else:
                    max_speed = MAX_VELOCITY

                velocity = body.linearVelocity
                speed = velocity.length
                if speed > max_speed:
                    body.linearVelocity = velocity * (max_speed / speed)
            elif body.userData and body.userData['type'] == 'asteroid':
                velocity = body.linearVelocity
                speed = velocity.length
                if speed > MAX_VELOCITY:
                    body.linearVelocity = velocity * (MAX_VELOCITY / speed)

        # 4. Deduct Energy: Subtract energy costs based on actual actions
        if self.energy_enabled:
            for i, player in enumerate(self.players):
                if i in energy_costs:
                    for ship_id, cost in energy_costs[i].items():
                        player.ships[ship_id].consume_energy(cost)

        # 5. Process Upgrades & Regeneration: For ships in-base, apply regeneration and valid upgrades
        if self.energy_enabled or self.upgrades_enabled:
            for i, player in enumerate(self.players):
                base_pos = b2Vec2(player.base_x / PPM, self.height / 2)

                # Process upgrades if enabled and commands exist
                if self.upgrades_enabled and i in energy_costs and actions[i] is not None:
                    # Look for upgrade commands within individual ship commands
                    player_actions = actions[i]
                    commands = player_actions.get("commands", [])
                    for command in commands:
                        if "upgrade" in command:
                            ship_id = command["ship_id"]
                            ship = player.ships[ship_id]
                            upgrade_type = command["upgrade"]

                            # Check if ship is in base
                            if ship.body:
                                ship_pos = ship.body.position
                                distance = (ship_pos - base_pos).length
                                if distance <= BASE_COLLECTION_RADIUS_UNITS / PPM:
                                    # Calculate upgrade cost
                                    current_level = ship.upgrades[upgrade_type]
                                    cost = 2 * (current_level + 1)

                                    # Check if player can afford and apply upgrade
                                    if player.spend_score(cost):
                                        ship.upgrades[upgrade_type] += 1
                                        player.last_score_change_tick = self.tick
                                        self.logger.debug(f"Player {i} upgraded ship {ship_id} {upgrade_type} to level {ship.upgrades[upgrade_type]} for {cost} points")

                # Process energy regeneration
                for ship in player.ships:
                    if ship.body:
                        ship_pos = ship.body.position
                        distance = (ship_pos - base_pos).length
                        if distance <= BASE_COLLECTION_RADIUS_UNITS / PPM:
                            if self.energy_enabled:
                                ship.regenerate_energy()

        for player in self.players:
            self.logger.debug(f"Player {player.id} state: {player.to_dict()}")

        # 6. Process Scoring & Spawning: Update scores and spawn new asteroids if needed
        self.check_base_collection()

        # Spawn new asteroids if needed
        while len(self.asteroids) < self.initial_asteroids:
            self.spawn_asteroid_pair()

        # Add replay data
        self.replay_data.append({
            'actions': actions,
            'state': self.to_dict()
        })

    def apply_push(self, ship: Ship, push_force_max: float = PUSH_FORCE_MAX):
        for asteroid in self.asteroids:
            direction = asteroid.body.position - ship.body.position
            distance = max(0, direction.length - SHIP_RADIUS_UNITS / PPM - ASTEROID_RADIUS_UNITS[asteroid.size] / PPM)
            if distance <= PUSH_RADIUS_UNITS / PPM:
                direction.Normalize()
                # Calculate push acceleration (decreases linearly with distance)
                push_strength = push_force_max * (1 - distance * PPM / PUSH_RADIUS_UNITS)
                # Convert to physics units and apply as force
                f_world = direction * push_strength
                asteroid.body.ApplyForceToCenter(f_world, True)

    def check_base_collection(self):
        for player in self.players:
            base_pos = b2Vec2(player.base_x / PPM, self.height / 2)
            for asteroid in self.asteroids[:]:
                direction = asteroid.body.position - base_pos
                if direction.length <= BASE_COLLECTION_RADIUS_UNITS / PPM:
                    # Store old score to check if it changed
                    old_score = player.score
                    player.score += {'small': 5, 'medium': 10, 'large': 20}[asteroid.size]

                    # Update the last score change tick
                    if player.score != old_score:
                        player.last_score_change_tick = self.tick

                    self.world.DestroyBody(asteroid.body)
                    self.asteroids.remove(asteroid)

    def _is_position_clear(self, pos, radius, extra_margin_units=5):
        """Return True if a circle at pos (physics units) with given radius (physics units)
        does not overlap any existing asteroid or ship. extra_margin_units adds a safety gap
        (in game units) on top of the sum of radii."""
        margin = extra_margin_units / PPM
        check_pos = b2Vec2(pos[0], pos[1])
        for asteroid in self.asteroids:
            asteroid_radius = ASTEROID_RADIUS_UNITS[asteroid.size] / PPM
            min_dist = radius + asteroid_radius + margin
            if (check_pos - asteroid.body.position).length < min_dist:
                return False
        for player in self.players:
            for ship in player.ships:
                ship_radius = SHIP_RADIUS_UNITS / PPM
                min_dist = radius + ship_radius + margin
                if (check_pos - ship.body.position).length < min_dist:
                    return False
        return True

    def spawn_asteroid_pair(self):
        size = random.choice(['small', 'medium', 'large'])
        radius = ASTEROID_RADIUS_UNITS[size] / PPM
        gap = 10
        max_attempts = 150
        for _ in range(max_attempts):
            pos = (random.uniform(gap, self.width - gap), random.uniform(gap, self.height - gap))
            mirror_pos = (self.width - pos[0], self.height - pos[1])
            if self._is_position_clear(pos, radius) and self._is_position_clear(mirror_pos, radius):
                self.spawn_asteroid(size, pos)
                self.spawn_asteroid(size, mirror_pos)
                return
        self.logger.warning(f"Could not find clear position for asteroid pair after {max_attempts} attempts, skipping")

    def spawn_asteroid_middle(self):
        size = random.choice(['small', 'medium', 'large'])
        radius = ASTEROID_RADIUS_UNITS[size] / PPM
        pos = (self.width / 2, self.height / 2)
        if self._is_position_clear(pos, radius):
            self.spawn_asteroid(size, pos)
        else:
            self.logger.warning("Could not spawn middle asteroid: center position is not clear, skipping")

    def spawn_asteroid(self, size, pos):
        body_def = b2BodyDef()
        body_def.type = b2_dynamicBody
        body_def.position = pos
        body_def.bullet = True
        body_def.fixedRotation = True
        body = self.world.CreateBody(body_def)

        # Get radius from constant
        radius = ASTEROID_RADIUS_UNITS[size] / PPM
        shape = b2CircleShape(radius=radius)

        fixture_def = b2FixtureDef(
            shape=shape,
            density=_density(ASTEROID_MASS[size], ASTEROID_RADIUS_UNITS[size]),
            friction=0.0,
            restitution=0.5,
            categoryBits=CATEGORY_ASTEROID,  # This fixture is in the ASTEROID category
            maskBits=CATEGORY_SHIP | CATEGORY_ASTEROID | CATEGORY_WALL  # It collides with ships, asteroids, and walls
        )
        body.CreateFixture(fixture_def)
        body.userData = {'type': 'asteroid'}
        asteroid = Asteroid(self._next_asteroid_id, body, size)
        self._next_asteroid_id += 1
        self.asteroids.append(asteroid)

    def get_input(self, player_id: int) -> str:
        return json.dumps({
            'turn': self.tick,
            'player': self.players[player_id].to_dict(self.energy_enabled, self.upgrades_enabled),
            'opponent': self.players[1 - player_id].to_dict(self.energy_enabled, self.upgrades_enabled),
            'asteroids': [asteroid.to_dict() for asteroid in self.asteroids]
        })

    def get_initial_info(self) -> Dict:
        info = {
            'width': GAME_WIDTH,
            'height': GAME_HEIGHT
        }
        if self.energy_enabled:
            info['energy_enabled'] = True
        if self.upgrades_enabled:
            info['upgrades_enabled'] = True
        return info

    def get_player_results(self) -> List[Dict[str, Any]]:
        """Generates the playerResults payload with hard-mode specific metadata."""
        sorted_player_indices = self.get_sorted_player_indices()

        # Create rank map that handles ties properly
        rank_map: Dict[int, int] = {}
        current_rank = 1
        for i, player_idx in enumerate(sorted_player_indices):
            if i > 0:
                prev_player = self.players[sorted_player_indices[i - 1]]
                current_player = self.players[player_idx]
                if (
                    current_player.score != prev_player.score
                    or current_player.last_score_change_tick != prev_player.last_score_change_tick
                ):
                    current_rank = i + 1
            rank_map[player_idx] = current_rank

        results: List[Dict[str, Any]] = []
        for i, player in enumerate(self.players):
            player_result: Dict[str, Any] = {
                'score': player.score,
                'lastScoreChangeTick': player.last_score_change_tick,
                'rank': rank_map.get(i, len(self.players)),
                'disqualified': not player.is_active,
                'reason': player.disqualification_reason or "Completed successfully",
            }

            if self.energy_enabled:
                player_result['shipEnergy'] = [ship.energy for ship in player.ships]
            if self.upgrades_enabled:
                player_result['shipUpgrades'] = [ship.upgrades.copy() for ship in player.ships]

            results.append(player_result)
        return results

    def get_sorted_player_indices(self) -> List[int]:
        """Sort players by score (descending) and last_score_change_tick (ascending).
        Returns list of player indices in sorted order."""
        indices = list(range(len(self.players)))
        indices.sort(
            key=lambda i: (self.players[i].score, -self.players[i].last_score_change_tick),
            reverse=True
        )
        return indices

    def get_winner_index(self) -> int:
        """Get the index of the winning player.
        Returns -1 if there are no players or if there is a tie."""
        if not self.players:
            return -1
        if len(self.players) == 2:
            if self.players[0].score == self.players[1].score and self.players[0].last_score_change_tick == self.players[1].last_score_change_tick:
                return -1
        return self.get_sorted_player_indices()[0]

    def is_game_over(self) -> bool:
        max_ticks = self.game_options.get('max_ticks', 1000)
        return self.tick >= max_ticks or all(not p.is_active for p in self.players)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'width': GAME_WIDTH,
            'height': GAME_HEIGHT,
            'tick': self.tick,
            'players': [player.to_dict(self.energy_enabled, self.upgrades_enabled) for player in self.players],
            'asteroids': [asteroid.to_dict() for asteroid in self.asteroids]
        }

    def update_from_replay(self, state_data: Dict[str, Any]):
        self.tick = state_data['tick']
        for i, player_data in enumerate(state_data['players']):
            self.players[i].update_from_dict(player_data)

        self.asteroids = []
        for asteroid_data in state_data['asteroids']:
            asteroid = Asteroid(asteroid_data['id'])
            asteroid.update_from_dict(asteroid_data)
            self.asteroids.append(asteroid)

    @classmethod
    def from_replay(cls, initial_state: Dict[str, Any], logger: logging.Logger = None):
        game_state = cls({'is_replay': True}, logger=logger)
        game_state.update_from_replay(initial_state)
        return game_state
