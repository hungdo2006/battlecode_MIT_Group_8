import { DEFAULT_RULE_SET } from "../src/config/defaultRuleSet.js";
import { columnName, squareName } from "../src/engine/coordinates.js";

// Historical standard-rule exports; the engine reads its own config.
export const BOARD_SIZE = DEFAULT_RULE_SET.board.rows;
export const FILES = Array.from({ length: DEFAULT_RULE_SET.board.columns }, (_, col) => columnName(col));

export const PLAYERS = {
  P1: "P1",
  P2: "P2",
};

export const PIECE_TYPES = Object.fromEntries(DEFAULT_RULE_SET.pieceTypes.map(({ id }) => [id.toUpperCase(), id]));

export const PIECE_LABELS = Object.fromEntries(DEFAULT_RULE_SET.pieceTypes.map(({ id, symbol }) => [id, symbol]));

// Stable asset paths for each player. To reskin later, replace only these
// 6 files in assets/pieces/ and keep the filenames unchanged.
export { PIECE_ASSETS } from "./pieceAssets.js";

export const TYPE_NAMES = Object.fromEntries(DEFAULT_RULE_SET.pieceTypes.map(({ id, name }) => [id, name]));

export const BEATS = Object.fromEntries(Object.entries(DEFAULT_RULE_SET.beats).map(([id, targets]) => [id, targets[0]]));

// Internal row 0 is rank 1; coordinates follow the configured goals.
export const GOALS = Object.fromEntries(Object.entries(DEFAULT_RULE_SET.goals).map(([player, goal]) =>
  [player, { ...goal, label: squareName(goal.row, goal.col) }]));

export const DEFAULT_ROOM_PREFIX = "ottv2";
export const STATE_VERSION = 2;
