"""Loads committed settings plus the local (gitignored) candidate profile."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass
class Config:
    settings: dict
    profile: dict
    do_not_repeat: dict
    output_dir: Path
    repo_root: Path = REPO_ROOT

    @property
    def models(self) -> dict:
        return self.settings["models"]


def _load_yaml(path: Path, required: bool) -> dict:
    if not path.exists():
        if required:
            raise FileNotFoundError(
                f"{path} not found. Copy {path.with_name(path.stem + '.example.yaml').name} and fill it in."
            )
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> Config:
    load_dotenv(REPO_ROOT / ".env")
    settings = _load_yaml(CONFIG_DIR / "settings.yaml", required=True)
    profile = _load_yaml(CONFIG_DIR / "profile.yaml", required=True)
    dnr = _load_yaml(CONFIG_DIR / "do_not_repeat.yaml", required=False)

    out = Path(os.environ.get("JOBHUNT_OUTPUT_DIR") or Path.home() / "JobHunt" / "output").resolve()
    # Resumes must never land inside the public repository.
    if out == REPO_ROOT or REPO_ROOT in out.parents:
        raise ValueError(f"JOBHUNT_OUTPUT_DIR ({out}) must be outside the repository {REPO_ROOT}")
    out.mkdir(parents=True, exist_ok=True)
    return Config(settings=settings, profile=profile, do_not_repeat=dnr, output_dir=out)
