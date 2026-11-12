"""Build an installable ZIP, including the integration's local brand images."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "alfaschool"


def main():
    destination = ROOT / "output" / "alfaschool-integration.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(INTEGRATION.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(ROOT))
    print(destination)


if __name__ == "__main__":
    main()
