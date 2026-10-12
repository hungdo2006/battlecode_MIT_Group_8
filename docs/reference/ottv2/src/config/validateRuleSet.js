export const PLAYER_IDS = Object.freeze(["P1", "P2"]);
export const WIN_CONDITION_IDS = Object.freeze(["reachGoal", "eliminatePieceType"]);
const object = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const slug = (v) => typeof v === "string" && /^[a-z][a-z0-9-]{0,63}$/.test(v);
const text = (v) => typeof v === "string" && v.trim().length > 0 && v.length <= 100;

export class ConfigValidationError extends Error {
  constructor(errors) {
    super(`Invalid RuleSet: ${errors.join("; ")}`);
    this.name = "ConfigValidationError";
    this.errors = errors;
  }
}

// Shared by Node and browser, without filesystem, DOM or networking dependencies.
export function validateRuleSet(config) {
  const errors = [];
  const check = (condition, message) => { if (!condition) errors.push(message); };
  if (!object(config)) throw new ConfigValidationError(["config must be an object"]);
  check(slug(config.id), "id must be a lowercase slug (1–64 characters)");
  check(text(config.name), "name must be non-empty and at most 100 characters");
  const { rows, columns } = config.board ?? {};
  check([rows, columns].every((n) => Number.isInteger(n) && n > 0 && n <= 100),
    "board rows and columns must be integers from 1 to 100");
  const position = (p) => object(p) && Number.isInteger(p.row) && Number.isInteger(p.col)
    && p.row >= 0 && p.row < rows && p.col >= 0 && p.col < columns;
  check(PLAYER_IDS.includes(config.turn?.firstPlayer), "turn.firstPlayer must be P1 or P2");
  check(Number.isInteger(config.movement?.maxSteps) && config.movement.maxSteps > 0
    && config.movement.maxSteps <= 100, "movement.maxSteps must be an integer from 1 to 100");
  const directions = config.movement?.directions;
  check(Array.isArray(directions) && directions.length > 0 && directions.length <= 8,
    "movement.directions must contain 1–8 unit directions");
  if (Array.isArray(directions)) {
    const seen = new Set();
    for (const d of directions) {
      const valid = Array.isArray(d) && d.length === 2 && d.every((n) => Number.isInteger(n) && Math.abs(n) <= 1)
        && (d[0] !== 0 || d[1] !== 0);
      check(valid, "each direction must be a non-zero [row, col] unit vector");
      if (valid) {
        check(!seen.has(d.join(",")), "movement.directions must not contain duplicates");
        seen.add(d.join(","));
      }
    }
  }
  const types = new Set();
  check(Array.isArray(config.pieceTypes) && config.pieceTypes.length > 0 && config.pieceTypes.length <= 32,
    "pieceTypes must contain 1–32 types");
  if (Array.isArray(config.pieceTypes)) {
    for (const type of config.pieceTypes) {
      check(object(type) && slug(type.id) && text(type.name), "pieceTypes entries need a valid id and name");
      if (!object(type)) continue;
      check(!types.has(type.id), `duplicate piece type: ${type.id}`);
      types.add(type.id);
      check(type.symbol === undefined || (typeof type.symbol === "string" && type.symbol.length <= 4),
        `invalid symbol for ${type.id}`);
    }
  }
  check(object(config.beats), "beats must be an object");
  if (object(config.beats)) {
    for (const [attacker, defenders] of Object.entries(config.beats)) {
      check(types.has(attacker), `unknown attacker type: ${attacker}`);
      check(Array.isArray(defenders) && defenders.every((id) => types.has(id) && id !== attacker),
        `invalid beat relationship for ${attacker}`);
    }
  }
  const conditions = config.winConditions;
  check(Array.isArray(conditions) && conditions.length > 0
    && conditions.every((id) => WIN_CONDITION_IDS.includes(id))
    && new Set(conditions).size === conditions.length, "winConditions must contain supported, unique condition ids");
  check(config.goals === undefined || object(config.goals), "goals must be an object");
  if (object(config.goals)) {
    for (const [player, goal] of Object.entries(config.goals)) {
      check(PLAYER_IDS.includes(player), `unknown goal player: ${player}`);
      check(position(goal), `goal for ${player} must be an integer position inside the board`);
    }
  }
  if (Array.isArray(conditions) && conditions.includes("reachGoal")) {
    for (const player of PLAYER_IDS) check(position(config.goals?.[player]), `missing valid goal for ${player}`);
  }
  check(object(config.startingPieces), "startingPieces must be an object");
  if (object(config.startingPieces)) {
    for (const player of Object.keys(config.startingPieces)) check(PLAYER_IDS.includes(player), `unknown player: ${player}`);
    const occupied = new Set();
    for (const player of PLAYER_IDS) {
      const pieces = config.startingPieces[player];
      check(Array.isArray(pieces) && pieces.length > 0, `startingPieces.${player} must contain at least one piece`);
      if (!Array.isArray(pieces)) continue;
      for (const piece of pieces) {
        check(position(piece), `starting position for ${player} must be inside the board`);
        check(types.has(piece?.type), `unknown starting piece type: ${piece?.type}`);
        if (!position(piece)) continue;
        const key = `${piece.row},${piece.col}`;
        check(!occupied.has(key), `overlapping starting position: ${key}`);
        occupied.add(key);
        const goal = config.goals?.[player];
        if (Array.isArray(conditions) && conditions.includes("reachGoal")) {
          check(!goal || piece.row !== goal.row || piece.col !== goal.col, `${player} cannot start on their own goal`);
        }
      }
      if (Array.isArray(conditions) && conditions.includes("eliminatePieceType")) {
        for (const type of types) check(pieces.some((p) => p?.type === type), `${player} must start with type ${type}`);
      }
    }
  }
  if (errors.length) throw new ConfigValidationError(errors);
  return config;
}
