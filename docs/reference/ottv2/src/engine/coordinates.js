export function columnName(col) {
  let name = "";
  for (let n = col + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(97 + (n - 1) % 26) + name;
  }
  return name;
}
export function squareName(row, col) { return `${columnName(col)}${row + 1}`; }
