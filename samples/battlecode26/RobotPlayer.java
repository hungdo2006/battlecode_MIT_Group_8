package arena;

import battlecode.common.*;

/** Minimal starter for the official Java 21 engine. */
public class RobotPlayer {
    public static void run(RobotController rc) throws GameActionException {
        Direction[] directions = {Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST};
        while (true) {
            for (Direction direction : directions) {
                if (rc.canMove(direction)) {
                    rc.move(direction);
                    break;
                }
            }
            Clock.yield();
        }
    }
}
