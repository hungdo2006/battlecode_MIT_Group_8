export function eliminatePieceType(state, piece, destination, config) {
  const opponent = piece.owner === "P1" ? "P2" : "P1";
  const remaining = new Set(state.board.flat().filter((p) => p?.owner === opponent).map((p) => p.type));
  const eliminated = config.pieceTypes.find((type) => !remaining.has(type.id));
  return eliminated
    ? { winner: piece.owner, reason: `${piece.owner} eliminated all opponent ${eliminated.name} pieces.` } : null;
}
