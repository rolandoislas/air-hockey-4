import os

import flask
import flask_sockets
import gevent
from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler

from src.game import Game

app = flask.Flask(__name__)
socket = flask_sockets.Sockets(app)
game = Game()


@app.route("/")
def web_index():
    return flask.render_template("game.html")


@socket.route("/state")
def socket_state(ws):
    game.add_state_socket(ws)
    while not ws.closed:
        gevent.sleep(0.1)


@socket.route("/request")
def socket_request(ws):
    game.add_request_socket(ws)

if __name__ == '__main__':
    server = pywsgi.WSGIServer(('', int(os.environ.get("PORT", 5000))), app, handler_class=WebSocketHandler)
    try:
        game.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
