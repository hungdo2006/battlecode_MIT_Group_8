"""Official Battlecode 2026 Python API. Uploaded as a single file."""


def turn():
    for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
        if rc.can_move(direction):
            rc.move(direction)
            break
