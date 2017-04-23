import ast
import os
import uuid
from collections import namedtuple

import construct
import gevent
import redis as rredis
import time

from client_socket import ClientSocket


class Game:
    command_id = namedtuple("packet_type",
                            ("register", "error", "update", "start", "state"))(
        register=0, error=1, update=2, start=3, state=4)
    players_struct = construct.Struct(
        "x" / construct.Int16ul,
        "y" / construct.Int16ul,
        "score" / construct.Int8ul,
        "active" / construct.Int8ul
    )
    command_state = construct.Struct(
        "puck_x" / construct.Int16ul,
        "puck_y" / construct.Int16ul,
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
                    for player in game["players"]:
                        if player["id"] == ws.get_id():
                            ws.send(self.build_state_packet(game), True)
            self.redis.set("games", games)
            gevent.sleep(0.05)

    @staticmethod
    def update_games(games):
        if len(games):
            games[0]["puck"]["x"] += 1

    def start(self):
        self.redis.set("games", [])
        gevent.spawn(self.update)

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
                if self.active_players(game["players"]) == 4:
                    for player in game["players"]:
                        for sock in self.sockets:
                            if sock.get_id() == player["id"]:
                                sock.send(self.command.build(dict(type=self.command_id.start)), True)
        # Create game if an open one was not found
        if not found_game:
            game = {
                "players": [],
                "puck": {"x": 0, "y": 0}
            }
            for player_num in range(0, 4):
                game["players"].append({"id": None, "x": 0, "y": 0, "score": 0, "active": 0})
            game["players"][0]["id"] = new_player_id
            game["players"][0]["active"] = 1
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
