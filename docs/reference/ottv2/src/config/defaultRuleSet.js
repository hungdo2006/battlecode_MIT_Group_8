import standard from "../../config/rules/standard-9x9.json" with { type: "json" };
import { validateRuleSet } from "./validateRuleSet.js";
export const DEFAULT_RULE_SET = validateRuleSet(standard);
