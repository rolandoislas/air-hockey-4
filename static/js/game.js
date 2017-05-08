var game = {};
game.command_id =  {"register": 0, "error": 1, "update": 2, "start": 3, "state": 4};
game.player_colors = ["#ff0700", "#ff9d00", "#3b00ff", "#12ff00"];
game.dimensions = {"size": 1000};

game.initializeCanvas = function () {
    var width = $(window).width();
    var height = $(window).height();
    game.table_size = width < height ? width : height;
    var puck_size = game.table_size * 0.05;
    var goal_size = game.table_size * 0.3;
    Crafty.init(game.table_size, game.table_size, $("#game")[0]);
    Crafty.background('#ebebeb');
    game.puck = Crafty.e("Puck, 2D, DOM, Color").attr({x: 0, y: 0, w: puck_size, h: puck_size}).color("#000000");
    game.players = [];
    for (var player = 0; player < 4; player++)
        game.players.push(Crafty.e("Player, 2D, DOM, Color")
            .attr({x: 0, y: 0, w: puck_size, h: puck_size})
            .color(game.player_colors[player]));
    game.goals = [];
    /*for (var goal = 0; goal < 4; goal++)
        game.goals.push(Crafty.e("Goal, 2D, DOM, Color")
            .attr({x: 500, y: 500, w: goal_size, h: goal_size})
            .color("#000000"));*/
};

game.onSocketStateOpened = function (event) {
    var register = [];
    register.push(Uint8Array.from([game.command_id.register]));
    register.push(game.client_id);
    game.socketState.send(new Blob(register));
};

game.scalePosition = function (size, isY) {
    var scaled = size * game.table_size / game.dimensions.size;
    if (isY)
        scaled = game.table_size - scaled;
    return scaled;
};

game.scalePlayer = function (player, playerPos) {
    var x = game.scalePosition(playerPos["x"]);
    var y = game.scalePosition(playerPos["y"], true);
    player.attr({x: x, y: y});
};

game.update_state = function (state) {
    game.puck.attr({x: game.scalePosition(state.puckX), y: game.scalePosition(state.puckY, true)});
    game.players.forEach(function (player) {
        var playerPos = state.players[game.players.indexOf(player)];
        game.scalePlayer(player, playerPos);
    })
};

game.startGame = function (command) {
    console.log("Starting game");
    game.playerNumber = command.playerNumber;
};

game.onSocketStateMessage = function (event) {
    var reader = new FileReader();
    reader.readAsArrayBuffer(event.data);
    reader.addEventListener("loadend", function(e) {
        var command = {};
        for (var t = 0; t < e.target.result.length; t++)
            console.log(e.target.result.length[t])
        command.type = new Uint8Array(e.target.result.slice(0))[0];
        // State update
        if (command.type === game.command_id.state) {
            command.puckX = new Int16Array(e.target.result.slice(1))[0];
            command.puckY = new Int16Array(e.target.result.slice(3))[0];
            command.players = [];
            for (var player_number = 0; player_number < 4; player_number++) {
                var pad = player_number * 7;
                command.players[player_number] = {};
                command.players[player_number].x = new Uint16Array(e.target.result.slice(5 + pad)[2])[0];
                command.players[player_number].y = new Uint16Array(e.target.result.slice(7 + pad)[2])[0];
                command.players[player_number].score = new Uint8Array(e.target.result.slice(9 + pad)[1])[0];
                command.players[player_number].active = new Uint8Array(e.target.result.slice(10 + pad)[1])[0];
                command.players[player_number].playerNumber = new Uint8Array(e.target.result.slice(11 + pad)[1])[0];
            }
            game.update_state(command);
        }
        else if (command.type === game.command_id.start) {
            command.playerNumber = new Uint8Array(e.target.result.slice(1)[0]);
            game.startGame(command);
        }
    });
};

game.initializeSocketState = function () {
    game.socketState = new WebSocket(window.location.protocol.replace("http", "ws") + "//" + window.location.hostname
        + ":" + window.location.port + "/state");
    game.socketState.onopen = game.onSocketStateOpened;
    game.socketState.onmessage = game.onSocketStateMessage;
    game.socketState.onclose = game.exit;
    game.socketState.onerror = game.exit;
};

game.onSocketRequestMessage = function (event) {
    var reader = new FileReader();
    reader.readAsArrayBuffer(event.data);
    reader.addEventListener("loadend", function(e) {
        var command = {};
        command.type = new Uint8Array(e.target.result.slice(0))[0];
        if (command.type === game.command_id.register) {
            command.id = e.target.result.slice(1);
            game.client_id = command.id;
            game.initializeSocketState();
        }
    });
};

game.onSocketRequestOpened = function (event) {
    var register = [];
    register.push(Uint8Array.from([game.command_id.register]));
    register.push("_".repeat(36)); // Empty id
    game.socketRequest.send(new Blob(register));
};

game.exit = function (event) {
    console.log(event);
};

game.initializeSocketRequest = function () {
    game.socketRequest = new WebSocket(window.location.protocol.replace("http", "ws") + "//" + window.location.hostname
        + ":" + window.location.port + "/request");
    game.socketRequest.onopen = game.onSocketRequestOpened;
    game.socketRequest.onmessage = game.onSocketRequestMessage;
    game.socketRequest.onclose = game.exit;
    game.socketRequest.onerror = game.exit;
};

game.ready = function () {
    game.initializeCanvas();
    game.initializeSocketRequest();
    $(window).resize(game.initializeCanvas);
};
$(document).ready(game.ready);