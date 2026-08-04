"""Entry point: `python -m depu_img_mcp` or the `depu-img-mcp` console script."""
from __future__ import annotations

from .config import load_config
from .server import run


def main() -> None:
    cfg = load_config()
    run(cfg)


if __name__ == "__main__":
    main()
