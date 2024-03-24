# IMPORTATION STANDARD
from pathlib import Path

# Installation related paths
HOME_DIRECTORY = Path.home()
PACKAGE_DIRECTORY = Path(__file__).parent.parent.parent
REPOSITORY_DIRECTORY = PACKAGE_DIRECTORY.parent

SETTINGS_DIRECTORY = HOME_DIRECTORY / ".quantflow"
SETTINGS_ENV_FILE = SETTINGS_DIRECTORY / ".env"
HIST_FILE_PATH = SETTINGS_DIRECTORY / ".quantflow.his"
