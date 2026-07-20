"""Seed the database with bundled data.

Currently a no-op: question-bank seeding lands in M3. The module exists so
the compose ``migrate`` service and upgrade docs stay stable.
"""

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger.info("no seed steps yet (question-bank seeding lands in M3)")


if __name__ == "__main__":
    main()
