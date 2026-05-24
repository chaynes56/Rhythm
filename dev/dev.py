"""dev.py -- Development utility"""

# todo add args parsing and help
# todo message if CWD isn't project root

import subprocess
from bumpversion.commands import bump
from bumpversion.config import get_configuration

config = get_configuration()
bump(["patch"], config)

# todo add git commit with error
subprocess.run(["git push"], check=True)

