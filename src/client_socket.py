import time

from geventwebsocket import WebSocketError


class ClientSocket:
    def __init__(self, ws):
        self.is_dead = False
        self.ws = ws
        self.client_id = None

    def is_closed(self):
        return self.ws.closed or self.is_dead

    def send(self, data, binary=None):
        try:
            self.ws.send(data, binary)
        except WebSocketError as e:
            if "dead" in e.message:
                self.is_dead = True

    def receive(self):
        return self.ws.receive()

    def close(self):
        self.ws.close()

    def set_id(self, client_id):
        self.client_id = client_id

    def get_id(self):
        return self.client_id
