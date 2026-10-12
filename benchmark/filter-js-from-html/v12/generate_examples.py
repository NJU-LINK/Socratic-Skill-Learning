import json
from pathlib import Path


def main() -> None:
    fixtures_path = Path("/app/data/fixtures.json")
    output_dir = Path("/app/examples")
    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures = json.loads(fixtures_path.read_text())
    for fixture in fixtures:
        output_path = output_dir / f"{fixture['name']}.html"
        output_path.write_text(fixture["html"])


if __name__ == "__main__":
    main()
