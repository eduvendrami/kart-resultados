"""Publica o site no GitHub Pages.

Gera data.json a partir do kart.db (sem as anotações pessoais) e envia index.html + data.json
para o repositório. Rode com:  python publicar.py   (ou dê dois cliques em "Publicar.bat")
"""
import json
import os
import subprocess
import sys
from datetime import datetime

import server

BASE = os.path.dirname(os.path.abspath(__file__))


def git(*args):
    return subprocess.run(["git", *args], cwd=BASE, capture_output=True, text=True, encoding="utf-8")


def main():
    races = server.list_races()
    for race in races:
        race.pop("notes", None)  # anotações (peso, clima, observações) ficam só no computador
    data = {"generated": datetime.now().isoformat(timespec="seconds"), "races": races}
    with open(os.path.join(BASE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"data.json gerado com {len(races)} sessões.")

    git("add", "index.html", "data.json")
    if not git("diff", "--cached", "--quiet").returncode:
        print("Nada mudou desde a última publicação.")
        return 0
    commit = git("commit", "-m", f"Atualiza resultados ({datetime.now():%d/%m/%Y %H:%M})")
    if commit.returncode:
        print(commit.stdout, commit.stderr)
        return 1
    push = git("push")
    if push.returncode:
        print(push.stdout, push.stderr)
        return 1
    print("Publicado! Em 1 ou 2 minutos o site online estará atualizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
