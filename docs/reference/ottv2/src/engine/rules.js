import { PLAYER_IDS } from "../config/validateRuleSet.js";
import { reachGoal } from "./winConditions/reachGoal.js";
import { eliminatePieceType } from "./winConditions/eliminatePieceType.js";
const winConditions = { reachGoal, eliminatePieceType };
const rulesFor = (state) => state.config;
const typeName = (config, id) => config.pieceTypes.find((type) => type.id === id)?.name ?? id;

export function inBounds(row, col, config) {
  return Number.isInteger(row) && Number.isInteger(col) && row >= 0 && col >= 0
    && row < config.board.rows && col < config.board.columns;
}
function movementVector(from, to, config) {
  if (!from || !to) return null;
  const dr = to.row - from.row, dc = to.col - from.col;
  return config.movement.directions.map(([row, col]) => {
    const steps = row !== 0 ? dr / row : dc / col;
    return Number.isInteger(steps) && steps > 0 && steps <= config.movement.maxSteps
      && dr === row * steps && dc === col * steps ? { row, col, steps } : null;
  }).find(Boolean) ?? null;
}
export function isAdjacent(from, to, config) { return Boolean(movementVector(from, to, config)); }
export function opponentOf(player) { return player === "P1" ? "P2" : player === "P2" ? "P1" : null; }
export function canCapture(attacker, defender, config) {
  if (!attacker || !defender || attacker.owner === defender.owner || attacker.type === defender.type) return false;
  return Object.hasOwn(config.beats, attacker.type) && config.beats[attacker.type].includes(defender.type);
}
export function validateMove(state, from, to, actor) {
  const config = rulesFor(state);
  const fail = (reason) => ({ ok: false, reason });
  if (!PLAYER_IDS.includes(actor)) return fail("Invalid player.");
  if (state.winner || state.status === "finished") return fail("The round is already over.");
  if (state.status === "waiting") return fail("Waiting for both player seats.");
  if (!from || !to || !inBounds(from.row, from.col, config) || !inBounds(to.row, to.col, config)) {
    return fail("Move must use integer positions inside the board.");
  }
  const vector = movementVector(from, to, config);
  if (!vector) return fail(`Move up to ${config.movement.maxSteps} step(s) in a configured direction.`);
  const piece = state.board[from.row][from.col], target = state.board[to.row][to.col];
  if (!piece) return fail("No piece is selected.");
  if (piece.owner !== actor) return fail("You can move only your own pieces.");
  if (state.turn !== actor) return fail("It is not your turn.");
  for (let step = 1; step < vector.steps; step += 1) {
    if (state.board[from.row + vector.row * step][from.col + vector.col * step]) return fail("A piece blocks the path.");
  }
  if (!target) return { ok: true, capture: false };
  if (target.owner === actor) return fail("Your own piece blocks this square.");
  if (target.type === piece.type) return fail("Two pieces of the same type cannot capture each other.");
  if (!canCapture(piece, target, config)) return fail(`${typeName(config, piece.type)} cannot capture ${typeName(config, target.type)}.`);
  return { ok: true, capture: true, captured: target };
}
export function getLegalMoves(state, from, actor) {
  const moves = [], config = rulesFor(state);
  if (!from || !inBounds(from.row, from.col, config)) return moves;
  for (const [dr, dc] of config.movement.directions) {
    for (let step = 1; step <= config.movement.maxSteps; step += 1) {
      const to = { row: from.row + dr * step, col: from.col + dc * step };
      if (!inBounds(to.row, to.col, config)) break;
      const verdict = validateMove(state, from, to, actor);
      if (verdict.ok) moves.push({ ...to, capture: verdict.capture });
      if (state.board[to.row][to.col]) break;
    }
  }
  return moves;
}
export function countPiecesByType(state, player) {
  const counts = Object.fromEntries(rulesFor(state).pieceTypes.map(({ id }) => [id, 0]));
  for (const row of state.board) for (const piece of row) {
    if (piece?.owner === player && Object.hasOwn(counts, piece.type)) counts[piece.type] += 1;
  }
  return counts;
}
export function detectWinner(state, movedPiece, destination) {
  const config = rulesFor(state);
  for (const id of config.winConditions) {
    const result = winConditions[id](state, movedPiece, destination, config);
    if (result) return result;
  }
  return null;
}
export function applyMove(state, from, to, actor) {
  const verdict = validateMove(state, from, to, actor);
  if (!verdict.ok) return verdict;
  const movingPiece = { ...state.board[from.row][from.col] }, capturedPiece = state.board[to.row][to.col];
  state.board[to.row][to.col] = movingPiece;
  state.board[from.row][from.col] = null;
  state.moveNumber += 1;
  state.revision = (state.revision ?? 0) + 1;
  state.lastMove = {
    from: { row: from.row, col: from.col }, to: { row: to.row, col: to.col },
    player: actor, pieceType: movingPiece.type,
    captured: capturedPiece ? { owner: capturedPiece.owner, type: capturedPiece.type } : null,
  };
  const result = detectWinner(state, movingPiece, to);
  if (result) {
    state.winner = result.winner;
    state.winReason = result.reason;
    state.status = "finished";
    state.scores[result.winner] += 1;
  } else { state.turn = opponentOf(actor); }
  return { ok: true, capture: Boolean(capturedPiece), winner: result?.winner ?? null };
}
