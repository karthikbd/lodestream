"""``python -m lodestream`` is the same as the ``lodestream`` command."""
import sys

from .cli import main

sys.exit(main())
