"""Ligne de commande de Penny (incrément 1 : analyse d'un dossier OneDrive, en lecture seule)."""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys

from . import db
from .config import Config, load_config
from .extract import LocalExtractor
from .llm import LLMError, Ollama
from .onedrive import OneDriveError, RcloneOneDrive
from .pipeline import Scanner
from .report import diag_text, status_text
from .search import Searcher, cards_listing

READONLY_SCOPES = "Files.Read offline_access"


def _guard_account() -> None:
    if os.environ.get("PENNY_ALLOW_ANY_USER") != "1" and getpass.getuser() != "penny":
        sys.exit("Penny doit tourner sous le compte « penny » (su - penny). "
                 "C'est ce qui empêche les autres programmes, dont Claude, de lire ses données.")


def _source(cfg: Config) -> RcloneOneDrive:
    return RcloneOneDrive(cfg.rclone_bin, cfg.rclone_remote, cfg.rclone_config, cfg.rclone_password_command)


def _llm(cfg: Config) -> Ollama:
    return Ollama(cfg.ollama_url, cfg.llm_model, cfg.embed_model)


def cmd_connect(cfg: Config, args) -> None:
    cfg.rclone_config.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(cfg.rclone_config.parent, 0o700)
    print(f"""Configuration de l'accès OneDrive en LECTURE SEULE (assistant rclone).
Fichier : {cfg.rclone_config}

Répondre ainsi :
  n) New remote — nom : {cfg.rclone_remote}
  Storage : onedrive — client_id et client_secret : laisser vides — region : global
  Edit advanced config? y — access_scopes : saisir exactement « {READONLY_SCOPES} »
    (si refusé : choisir « Read only access to all resources »)
  Les autres options avancées : laisser par défaut
  Use web browser to automatically authenticate? n
    → rclone affiche une commande « rclone authorize … » : la lancer dans VOTRE session
      (votre compte, avec navigateur), vérifier que Microsoft n'affiche que des droits de LECTURE,
      puis coller ici le jeton obtenu
  Type de compte : OneDrive (personnel)
  Puis : s) Set configuration password — choisir un mot de passe (configuration chiffrée)
""")
    env = dict(os.environ, RCLONE_CONFIG=str(cfg.rclone_config))
    subprocess.run([cfg.rclone_bin, "config"], env=env, check=False)
    if cfg.rclone_config.exists():
        os.chmod(cfg.rclone_config, 0o600)
    print("Vérification : penny onedrive check")


def cmd_check(cfg: Config, args) -> None:
    print(_source(cfg).check())
    print("Accès OneDrive : OK")


def cmd_scan(cfg: Config, args) -> None:
    conn = db.connect(cfg.db_path)
    scanner = Scanner(conn, _source(cfg), LocalExtractor(), _llm(cfg), cfg.cache_dir, cfg.markdown_dir,
                      cfg.max_file_mb)
    def progress(n: int, total: int) -> None:
        print(f"\r  traitement {n}/{total}…", end="", file=sys.stderr, flush=True)
    print(f"Inventaire de « {args.root} »…")
    rep = scanner.scan(args.root, limit=args.limit, progress=progress)
    print(file=sys.stderr)
    print(f"Inventaire : {rep.listed} fichiers ({rep.new} nouveaux, {rep.changed} modifiés, "
          f"{rep.moved} déplacés ou renommés, {rep.gone} disparus)")
    print(f"Ce passage : {rep.processed} analysés, {rep.no_text} sans texte, {rep.skipped} ignorés, "
          f"{rep.errors} en erreur" + (f" {rep.error_codes}" if rep.error_codes else ""))
    print(f"Reste à traiter : {rep.remaining}" + (" — relancer la même commande pour continuer" if rep.remaining else ""))


def cmd_status(cfg: Config, args) -> None:
    print(status_text(db.connect(cfg.db_path), args.root))


def cmd_docs(cfg: Config, args) -> None:
    rows = cards_listing(db.connect(cfg.db_path), args.root, args.type, args.sans_texte)
    for r in rows:
        if r["doc_type"]:
            who = ", ".join(r["parties"][:3])
            print(f"{r['doc_date'] or '????-??-??'}  {r['doc_type'][:18]:<18} {r['title'] or ''}"
                  + (f" — {who}" if who else "") + f"\n            {r['root'].strip('/')}/{r['path']}")
        else:
            state = r["state"] or "en attente"
            print(f"{'':10}  {'(' + state + ')':<18} {r['root'].strip('/')}/{r['path']}")
    print(f"\n{len(rows)} fichiers.")


def cmd_ask(cfg: Config, args) -> None:
    ans = Searcher(db.connect(cfg.db_path), _llm(cfg)).ask(args.question, args.root)
    print(ans.text)
    if ans.sources:
        print("\nSources :")
        for n, s in enumerate(ans.sources, 1):
            print(f"  [{n}] {s.path}" + (f" ({s.doc_date})" if s.doc_date else ""))
    print(f"\n{ans.perimeter}")


def cmd_diag(cfg: Config, args) -> None:
    print(diag_text(db.connect(cfg.db_path), cfg.llm_model, cfg.embed_model))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="penny", description="Penny — seconde mémoire locale")
    sub = parser.add_subparsers(dest="cmd", required=True)
    od = sub.add_parser("onedrive", help="accès OneDrive (lecture seule)")
    od_sub = od.add_subparsers(dest="action", required=True)
    od_sub.add_parser("connect", help="configurer l'accès (une fois)").set_defaults(func=cmd_connect)
    od_sub.add_parser("check", help="vérifier l'accès").set_defaults(func=cmd_check)
    p = sub.add_parser("scan", help="inventorier et analyser un dossier OneDrive")
    p.add_argument("root", help="dossier OneDrive, ex. « Documents/Administratif »")
    p.add_argument("--limit", type=int, default=None, help="nombre maximal de fichiers à analyser ce passage")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("status", help="état de l'analyse")
    p.add_argument("root", nargs="?")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("docs", help="inventaire des documents")
    p.add_argument("root", nargs="?")
    p.add_argument("--type", help="filtrer par type (facture, contrat…)")
    p.add_argument("--sans-texte", action="store_true", help="seulement les scans et photos sans texte")
    p.set_defaults(func=cmd_docs)
    p = sub.add_parser("ask", help="poser une question")
    p.add_argument("question")
    p.add_argument("--root", help="limiter à un dossier analysé")
    p.set_defaults(func=cmd_ask)
    sub.add_parser("diag", help="rapport ANONYMISÉ (le seul à transmettre à Claude)").set_defaults(func=cmd_diag)

    args = parser.parse_args(argv)
    _guard_account()
    cfg = load_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cfg.data_dir, 0o700)
    try:
        args.func(cfg, args)
    except (OneDriveError, LLMError) as exc:
        sys.exit(f"Erreur : {exc}")
    except KeyboardInterrupt:
        sys.exit("\nInterrompu. Relancer la même commande reprend où elle s'était arrêtée.")


if __name__ == "__main__":
    main()
