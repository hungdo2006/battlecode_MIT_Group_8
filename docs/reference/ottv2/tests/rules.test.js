import test from "node:test";
import assert from "node:assert/strict";

import { BEATS } from "../js/constants.js";
import {
  applyMove,
  canCapture,
  countPiecesByType,
  getLegalMoves,
  isAdjacent,
  validateMove,
} from "../js/rules.js";
import { createInitialGameState } from "../js/state.js";

test("initial setup has 3 pieces of each type per player", () => {
  const state = createInitialGameState();
  assert.deepEqual(countPiecesByType(state, "P1"), {
    rock: 3,
    paper: 3,
    scissors: 3,
  });
  assert.deepEqual(countPiecesByType(state, "P2"), {
    rock: 3,
    paper: 3,
    scissors: 3,
  });
});

test("pieces move only one square in 8 directions", () => {
  assert.equal(isAdjacent({ row: 4, col: 4 }, { row: 5, col: 5 }), true);
  assert.equal(isAdjacent({ row: 4, col: 4 }, { row: 4, col: 5 }), true);
  assert.equal(isAdjacent({ row: 4, col: 4 }, { row: 6, col: 4 }), false);
  assert.equal(isAdjacent({ row: 4, col: 4 }, { row: 4, col: 4 }), false);
});

test("RPS capture cycle is correct", () => {
  for (const [attackerType, defenderType] of Object.entries(BEATS)) {
    assert.equal(
      canCapture(
        { owner: "P1", type: attackerType },
        { owner: "P2", type: defenderType }
      ),
      true
    );
  }
});

test("same types cannot capture each other", () => {
  assert.equal(
    canCapture(
      { owner: "P1", type: "rock" },
      { owner: "P2", type: "rock" }
    ),
    false
  );
});

test("weaker piece cannot move onto stronger enemy", () => {
  const state = createInitialGameState();
  state.board[4][4] = { id: "a", owner: "P1", type: "scissors" };
  state.board[5][5] = { id: "b", owner: "P2", type: "rock" };

  const verdict = validateMove(
    state,
    { row: 4, col: 4 },
    { row: 5, col: 5 },
    "P1"
  );
  assert.equal(verdict.ok, false);
});

test("legal move generation never returns a square more than one step away", () => {
  const state = createInitialGameState();
  state.board[4][4] = { id: "center", owner: "P1", type: "rock" };
  const moves = getLegalMoves(state, { row: 4, col: 4 }, "P1");
  assert.ok(moves.length <= 8);
  assert.ok(
    moves.every(
      (move) =>
        Math.abs(move.row - 4) <= 1 &&
        Math.abs(move.col - 4) <= 1 &&
        !(move.row === 4 && move.col === 4)
    )
  );
});

test("P1 wins by reaching i9", () => {
  const state = createInitialGameState();
  state.board[7][7] = { id: "goal-runner", owner: "P1", type: "paper" };
  state.board[8][8] = null;

  const result = applyMove(
    state,
    { row: 7, col: 7 },
    { row: 8, col: 8 },
    "P1"
  );

  assert.equal(result.ok, true);
  assert.equal(state.winner, "P1");
  assert.match(state.winReason, /i9/);
});

test("capturing the last enemy piece of one type wins", () => {
  const state = createInitialGameState();

  // Keep only the P2 scissors on h9.
  state.board[8][1] = null;
  state.board[8][4] = null;
  state.board[7][7] = { id: "finisher", owner: "P1", type: "rock" };

  const result = applyMove(
    state,
    { row: 7, col: 7 },
    { row: 8, col: 7 },
    "P1"
  );

  assert.equal(result.ok, true);
  assert.equal(state.winner, "P1");
  assert.match(state.winReason, /Scissors/);
});
