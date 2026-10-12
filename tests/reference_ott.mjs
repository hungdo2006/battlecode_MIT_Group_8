// Only the retained pure rule/state modules are imported. No playhtml, server,
// Express or Socket.IO dependency is executed or needed by this oracle.
import { readFileSync } from 'node:fs';
import { createInitialGameState } from '../docs/reference/ottv2/js/state.js';
import { validateMove, applyMove } from '../docs/reference/ottv2/js/rules.js';
const cases = JSON.parse(readFileSync(0, 'utf8'));
const owner = p => p === 'A' ? 'P1' : p === 'B' ? 'P2' : p;
const outputs = cases.map(item => {
  const state = createInitialGameState();
  state.board = item.state.board.map(row => row.map(piece => piece ? { ...piece, owner: owner(piece.owner) } : null));
  state.turn = owner(item.state.current_player);
  state.moveNumber = item.state.round_turn;
  const verdict = validateMove(state, item.action.from, item.action.to, owner(item.player));
  if (!verdict.ok) return { ok: false };
  applyMove(state, item.action.from, item.action.to, owner(item.player));
  return { ok: true, winner: state.winner === 'P1' ? 'A' : state.winner === 'P2' ? 'B' : null,
    board: state.board.map(row => row.map(piece => piece ? { ...piece, owner: piece.owner === 'P1' ? 'A' : 'B' } : null)) };
});
process.stdout.write(JSON.stringify(outputs));
