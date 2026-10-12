import { validateRuleSet } from "../config/validateRuleSet.js";

export function createInitialBoard(config) {
  validateRuleSet(config);
  const board = Array.from({ length: config.board.rows }, () => Array(config.board.columns).fill(null));
  for (const [owner, pieces] of Object.entries(config.startingPieces)) {
    pieces.forEach(({ row, col, type }, index) => {
      board[row][col] = { id: `${owner.toLowerCase()}-${type}-${index + 1}`, owner, type };
    });
  }
  return board;
}
export function updateStatus(state) {
  state.status = state.winner ? "finished" : state.players.P1 && state.players.P2
    && state.players.P1.connected !== false && state.players.P2.connected !== false ? "playing" : "waiting";
}
export function createInitialGameState({ online = false, config, id = "local", roomId = null } = {}) {
  const ruleSet = structuredClone(validateRuleSet(config));
  return {
    version: 2, id, roomId, ruleSetId: ruleSet.id, config: ruleSet,
    board: createInitialBoard(ruleSet), turn: ruleSet.turn.firstPlayer,
    winner: null, winReason: null, round: 1, moveNumber: 0, revision: 0, lastMove: null,
    players: online ? { P1: null, P2: null } : {
      P1: { name: "Player 1", connectionId: "local-p1" },
      P2: { name: "Player 2", connectionId: "local-p2" },
    },
    scores: { P1: 0, P2: 0 }, status: online ? "waiting" : "playing",
  };
}
function restartBoard(state) {
  state.board = createInitialBoard(state.config);
  state.turn = state.config.turn.firstPlayer;
  state.winner = null;
  state.winReason = null;
  state.moveNumber = 0;
  state.lastMove = null;
  state.revision = (state.revision ?? 0) + 1;
  updateStatus(state);
}
export function resetRound(state) { restartBoard(state); state.round += 1; }
export function hardReset(state, { keepPlayers = true } = {}) {
  if (!keepPlayers) state.players = { P1: null, P2: null };
  restartBoard(state);
  state.round = 1;
  state.scores = { P1: 0, P2: 0 };
}
