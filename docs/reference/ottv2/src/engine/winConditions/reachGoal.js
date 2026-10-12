import { squareName } from "../coordinates.js";
export function reachGoal(state, piece, destination, config) {
  const goal = config.goals?.[piece.owner];
  return goal && goal.row === destination.row && goal.col === destination.col
    ? { winner: piece.owner, reason: `${piece.owner} reached ${squareName(goal.row, goal.col)}.` } : null;
}
