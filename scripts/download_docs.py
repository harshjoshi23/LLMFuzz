#!/usr/bin/env python3
"""
Automatic Documentation Downloader

Downloads documentation and READMEs from the evaluation repositories
so they can be embedded into the vectorstore for LLM seed generation.

Targets downloaded:
- LibreSolar BMS
- LibreSolar Charge Controller
- Infineon optimizer example

Output directory:
    data/docs/<project>/
"""

import pathlib
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC_DIR = ROOT / "data" / "docs"

SOURCES = {
    "libresolar_bms": "https://raw.githubusercontent.com/LibreSolar/bms-firmware/main/README.md",
    "libresolar_charge": "https://raw.githubusercontent.com/LibreSolar/charge-controller-firmware/main/README.md",
    "infineon_optimizer": "https://raw.githubusercontent.com/Infineon/mtb-example-pwrlib-dc-optimizer/master/README.md",
}


def ensure_dirs():
    DOC_DIR.mkdir(parents=True, exist_ok=True)


def download_docs():
    for name, url in SOURCES.items():
        project_dir = DOC_DIR / name
        project_dir.mkdir(parents=True, exist_ok=True)

        out_file = project_dir / "README.md"
        print(f"[Docs] downloading {url}")

        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            out_file.write_text(r.text)
            print(f"[Docs] saved -> {out_file}")
        except Exception as e:
            print(f"[Docs] failed {url}: {e}")


if __name__ == "__main__":
    ensure_dirs()
    download_docs()
