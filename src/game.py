import ast
import os
import random
import sys
import uuid
from collections import namedtuple

import construct
import gevent
import redis as rredis
import time

from client_socket import ClientSocket
from src.rect import Rect


class Game:
    command_id = namedtuple("packet_type",
                            ("register", "error", "update", "start", "state"))(
        register=0, error=1, update=2, start=3, state=4)
    players_struct = construct.Struct(
        "x" / construct.Int16ul,
        "y" / construct.Int16ul,
        "score" / construct.Int8ul,
        "active" / construct.Int8ul,
        "player_num" / construct.Int8ul
    )
    command_state = construct.Struct(
        "puck_x" / construct.Int16sl,
        "puck_y" / construct.Int16sl,
        "players" / construct.Array(4, players_struct)
    )
    command_update = construct.Struct(
        "x" / construct.Int16ul,
        "y" / construct.Int16ul
    )
    command_register = construct.Struct(
        "id" / construct.String(36)
    )
    command = construct.Struct(
        "type" / construct.Int8ul,
        construct.Embedded(
            construct.Switch(lambda ctx: ctx.type, {
                                 command_id.update: command_update,
                                 command_id.register: command_register,
                                 command_id.state: command_state,
                             },
                             default=construct.Pass
                             )
        )
    )
    dimensions = namedtuple("dimensions", ("table_size", "puck_size", "goal_size"))(table_size=1000, puck_size=50,
                                                                                    goal_size=300)

    def __init__(self):
        self.sockets = []
        self.redis = rredis.from_url(os.environ.get("REDIS_URL"))

    def add_state_socket(self, ws):
        sock = ClientSocket(ws)
        data = sock.receive()
        if data:
            data = self.command.parse(data)
        if data and data.type == self.command_id.register:
            sock.set_id(data.id)
            self.sockets.append(sock)
        else:
            sock.close()

    def update(self):
        while True:
            games = ast.literal_eval(self.redis.get("games"))
            self.update_games(games)
            # Send states
            for ws in list(self.sockets):
                # Clear inactive sockets
                if ws.is_closed():
                    for game in list(games):
                        for player in range(0, len(game["players"])):
                            if game["players"][player]["id"] == ws.get_id():
                                game["players"][player]["id"] = None
                                game["players"][player]["active"] = 0
                        if self.active_players(game["players"]) == 0:
                            games.remove(game)
                    self.sockets.remove(ws)
                    continue
                # Send state
                for game in games:
                    if not game["active"]:
                        continue
                    for player in game["players"]:
                        if player["id"] == ws.get_id():
                            ws.send(self.build_state_packet(game), True)
            self.redis.set("games", games)
            gevent.sleep(0.05)

    def update_games(self, games):
        for game in games:
            if not game["active"]:
                continue
            # Move
            degree = game["puck"]["degree"]
            main_direction = int(round(degree / 90.))
            offset = degree - main_direction * 90
            move_amount = 500 * (time.time() - game["update_time"])
            game["update_time"] = time.time()
            if main_direction == 0:
                if offset == 0:
                    game["puck"]["y"] += move_amount
                else:
                    game["puck"]["x"] += move_amount + offset
                    game["puck"]["y"] += move_amount + offset
            elif main_direction == 1:
                if offset == 0:
                    game["puck"]["x"] += move_amount
                else:
                    game["puck"]["x"] += move_amount + offset
                    game["puck"]["y"] -= move_amount + offset
            elif main_direction == 2:
                if offset == 0:
                    game["puck"]["y"] -= move_amount
                else:
                    game["puck"]["x"] -= move_amount + offset
                    game["puck"]["y"] -= move_amount + offset
            elif main_direction == 3:
                if offset == 0:
                    game["puck"]["x"] -= move_amount
                else:
                    game["puck"]["x"] -= move_amount + offset
                    game["puck"]["y"] += move_amount + offset
            # Wall check
            puck = Rect(game["puck"]["x"], game["puck"]["y"], self.dimensions.puck_size, self.dimensions.puck_size)
            if puck.right >= self.dimensions.table_size:
                game["puck"]["degree"] = self.calculate_degree(degree, 1)
            elif puck.left <= 0:
                game["puck"]["degree"] = self.calculate_degree(degree, 3)
            elif puck.top >= self.dimensions.table_size:
                game["puck"]["degree"] = self.calculate_degree(degree, 0)
            elif puck.bottom <= 0:
                game["puck"]["degree"] = self.calculate_degree(degree, 2)
            # Goal check
            goal_protrude = 20
            # left
            if puck.overlaps(Rect(0, self.dimensions.table_size / 2, goal_protrude, self.dimensions.goal_size)):
                game["players"][3]["score"] += 1
                self.reset_puck(game)
            # right
            elif puck.overlaps(Rect(self.dimensions.table_size - self.dimensions.puck_size,
                                    self.dimensions.table_size / 2, goal_protrude, self.dimensions.goal_size)):
                game["players"][1]["score"] += 1
                self.reset_puck(game)
            # top
            elif puck.overlaps(Rect(self.dimensions.table_size / 2, self.dimensions.table_size,
                                    self.dimensions.goal_size, goal_protrude)):
                game["players"][0]["score"] += 1
                self.reset_puck(game)
            # bottom
            elif puck.overlaps(Rect(self.dimensions.table_size / 2, 0, self.dimensions.goal_size, goal_protrude)):
                game["players"][2]["score"] += 1
                self.reset_puck(game)
            # Bounds check
            if game["puck"]["x"] < -self.dimensions.puck_size:
                game["puck"]["x"] = -self.dimensions.puck_size
            if game["puck"]["y"] < -self.dimensions.puck_size:
                game["puck"]["y"] = -self.dimensions.puck_size
            if game["puck"]["x"] > self.dimensions.table_size + self.dimensions.puck_size:
                game["puck"]["x"] = self.dimensions.table_size + self.dimensions.puck_size
            if game["puck"]["y"] > self.dimensions.table_size + self.dimensions.puck_size:
                game["puck"]["y"] = self.dimensions.table_size + self.dimensions.puck_size

    def start(self):
        self.redis.set("games", [])
        gevent.spawn(self.update).link_exception(sys.exit)

    def add_request_socket(self, ws):
        sock = ClientSocket(ws)
        while not sock.is_closed():
            data = sock.receive()
            if not data:
                sock.close()
                return
            data = self.command.parse(data)
            # Register
            if data and data.type == self.command_id.register and sock.get_id() is None:
                client_id = self.get_new_client_id()
                sock.set_id(client_id)
                if client_id:
                    sock.send(self.command.build(dict(type=self.command_id.register, id=client_id)), True)
                else:
                    sock.send(self.command.build(dict(type=self.command_id.error)), True)
            # Position Update
            elif data.type == self.command_id.update:
                self.update_player_position(sock.client_id, data.x, data.y)

    def get_new_client_id(self):
        games = ast.literal_eval(self.redis.get("games"))
        new_player_id = str(uuid.uuid4())
        # Make sure the id is unique
        for game in games:
            for player in game["players"]:
                if player["id"] == new_player_id:
                    return self.get_new_client_id()
        # Find an open game
        found_game = False
        for game in games:
            if self.active_players(game["players"]) < 4:
                found_game = True
                # Add player to game
                for player in range(0, len(game["players"])):
                    if game["players"][player]["active"] == 0:
                        game["players"][player]["id"] = new_player_id
                        game["players"][player]["active"] = 1
                        break
                # Check if game can start
                if self.active_players(game["players"]) == 4:  # TODO allow games to start with less than 4 players
                    game["active"] = 1
                    game["update_time"] = time.time()
                    game["puck"]["x"] = self.dimensions.table_size / 2
                    game["puck"]["y"] = self.dimensions.table_size / 2
                    game["puck"]["degree"] = random.randint(0, 3) * 90
                    for player in game["players"]:
                        for sock in self.sockets:
                            if sock.get_id() == player["id"]:
                                sock.send(self.command.build(dict(type=self.command_id.start,
                                                                  player_num=player["player_num"])), True)
        # Create game if an open one was not found
        if not found_game:
            game = {
                "players": [],
                "puck": {"x": 0, "y": 0, "degree": 0},
                "active": 0,
                "update_time": 0
            }
            for player_num in range(0, 4):
                # noinspection PyTypeChecker
                game["players"].append({"id": None, "x": self.dimensions.table_size / 2, "y": 10,
                                        "score": 0, "active": 0, "player_num": player_num})
            game["players"][0]["id"] = new_player_id
            game["players"][0]["active"] = 1
            # debug
            game["active"] = 1
            game["update_time"] = time.time()
            game["puck"]["x"] = self.dimensions.table_size / 2
            game["puck"]["y"] = self.dimensions.table_size / 2
            game["puck"]["degree"] = random.randint(0, 3) * 90
            # noinspection PyTypeChecker
            for player in game["players"]:
                for sock in self.sockets:
                    # noinspection PyTypeChecker
                    if sock.get_id() == player["id"]:
                        sock.send(self.command.build(dict(type=self.command_id.start)), True)
            # debug
            games.append(game)
        self.redis.set("games", games)
        return new_player_id

    def build_state_packet(self, game):
        state = dict(type=self.command_id.state, puck_x=game["puck"]["x"], puck_y=game["puck"]["y"],
                     players=game["players"])
        return self.command.build(state)

    def update_player_position(self, client_id, x, y):
        games = ast.literal_eval(self.redis.get("games"))
        for game in games:
            for player in game["players"]:
                if player["id"] == client_id:
                    player["x"] = x
                    player["y"] = y
        self.redis.set("games", games)

    @staticmethod
    def active_players(players):
        count = 0
        for player in players:
            if player["active"] == 1:
                count += 1
        return count

    @staticmethod
    def calculate_degree(degree, direction):
        if degree in (0, 90, 180, 270) or degree >= 360 or degree < 0:
            return random.randint(0, 359)
        if direction == 0:
            if degree < 90:
                return degree + 90
            elif 360 > degree > 270:
                return degree - 90
        elif direction == 1:
            if degree < 90:
                return degree + 270
            elif degree < 180:
                return degree + 90
        elif direction == 2:
            if degree < 180:
                return degree - 90
            elif degree < 270:
                return degree + 90
        elif direction == 3:
            if degree < 270:
                return degree - 90
            elif degree < 360:
                return degree - 270
        return random.randint(0, 359)

    def reset_puck(self, game):
        game["puck"]["x"] = self.dimensions.table_size / 2
        game["puck"]["y"] = self.dimensions.table_size / 2
        game["puck"]["degree"] = random.randint(0, 3) * 90
