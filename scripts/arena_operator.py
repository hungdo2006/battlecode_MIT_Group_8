"""Stable operator command for NEON ARENA's existing EC2 installation.

This is an interface-only alias. The underlying tested runner controller
continues to use its original Docker project, volumes and private state.
Renaming those identifiers would require a separate migration and restore drill.
"""

from scripts import b15_pilot_runner


def main(argv=None):
    return b15_pilot_runner.main(argv)


if __name__ == "__main__":
    main()
