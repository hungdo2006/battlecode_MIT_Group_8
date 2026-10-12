// Historical convenience defaults; all rule implementation stays in the engine.
import { DEFAULT_RULE_SET } from '../src/config/defaultRuleSet.js';
import * as rules from '../src/engine/rules.js';
export { applyMove, validateMove, getLegalMoves, countPiecesByType, detectWinner, opponentOf } from '../src/engine/rules.js';
export function inBounds(row, col, config = DEFAULT_RULE_SET) { return rules.inBounds(row, col, config); }
export function isAdjacent(from, to, config = DEFAULT_RULE_SET) { return rules.isAdjacent(from, to, config); }
export function canCapture(attacker, defender, config = DEFAULT_RULE_SET) { return rules.canCapture(attacker, defender, config); }
