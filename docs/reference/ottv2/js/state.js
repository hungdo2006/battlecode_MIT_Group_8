import { DEFAULT_RULE_SET } from '../src/config/defaultRuleSet.js';
import * as state from '../src/engine/state.js';
export { hardReset, resetRound, updateStatus } from '../src/engine/state.js';
export function createInitialBoard(config = DEFAULT_RULE_SET) { return state.createInitialBoard(config); }
export function createInitialGameState(options = {}) {
  return state.createInitialGameState({ config: DEFAULT_RULE_SET, ...options });
}
