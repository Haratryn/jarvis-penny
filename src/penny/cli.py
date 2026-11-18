"""Ligne de commande de Penny (incrément 1 : analyse d'un dossier OneDrive, en lecture seule)."""
from __future__ import annotations

import argparse
import os
import pwd
import sqlite3
import subprocess
import sys

from . import db
from .config import Config, load_config
from .extract import LocalExtractor
from .llm import LLMError, Ollama
from .localfolder import LocalFolderSource
from .onedrive import OneDriveError, RcloneOneDrive
from .pipeline import InventoryAborted, Scanner
from .progress import Progress
from .report import diag_text, status_text
from .search import Searcher, cards_listing

READONLY_SCOPES = "Files.Read offline_access"


def installed_version() -> str:
    """Version et commit déployé (dossier /opt/penny/releases/<commit>)."""
    from pathlib import Path
    from . import __version__
    for part in Path(__file__).resolve().parts:
        if len(part) == 12 and all(c in "0123456789abcdef" for c in part):
            return f"{__version__} (commit {part})"
    return f"{__version__} (développement)"


def current_account() -> str:
    """Compte réel du processus (identifiant effectif), pas les variables USER/LOGNAME,
    qu'un su peut laisser au nom de l'appelant et que n'importe qui peut modifier."""
    return pwd.getpwuid(os.geteuid()).pw_name


def _guard_account() -> None:
    account = current_account()
    if os.environ.get("PENNY_ALLOW_ANY_USER") != "1" and account != "penny":
        sys.exit(f"Penny doit tourner sous le compte « penny » (compte actuel : {account}). "
                 "Lancer d'abord : su - penny. "
                 "C'est ce qui empêche les autres programmes, dont Claude, de lire ses données.")


def _source(cfg: Config, conn=None):
    if cfg.source == "local":
        return LocalFolderSource(cfg.local_root, conn or db.connect(cfg.db_path), cfg.max_file_mb)
    if cfg.source == "rclone":
        return RcloneOneDrive(cfg.rclone_bin, cfg.rclone_remote, cfg.rclone_config, cfg.rclone_password_command)
    sys.exit(f"PENNY_SOURCE inconnu : {cfg.source} (attendu : local ou rclone)")


def _llm(cfg: Config) -> Ollama:
    return Ollama(cfg.ollama_url, cfg.llm_model, cfg.embed_model)


def cmd_connect(cfg: Config, args) -> None:
    if cfg.source != "rclone":
        sys.exit("Source « dossier local » : aucune connexion à configurer (tutoriel, étape 11.3).")
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
    source = _source(cfg)
    if cfg.source == "local" and args.dossier:
        print(f"Diagnostic de « {args.dossier} » vu par penny (reste sur votre écran) :")
        for label, state in source.diagnose(args.dossier):
            print(f"  {label:<40} {state}")
        print("Attendu : « traversable seulement » pour les niveaux intermédiaires, "
              "« ok : traversable et lisible » pour le dossier choisi.")
        return
    print(source.check())
    print(f"Source : {cfg.source} — accès OneDrive : OK")


def cmd_scan(cfg: Config, args) -> None:
    conn = db.connect(cfg.db_path)
    scanner = Scanner(conn, _source(cfg, conn), LocalExtractor(), _llm(cfg), cfg.cache_dir, cfg.markdown_dir,
                      cfg.max_file_mb)
    progress = Progress(details=args.details)
    print(f"Inventaire de « {args.root} »…")
    try:
        rep = scanner.scan(args.root, limit=args.limit, progress=progress, accept_gone=args.confirmer_disparitions)
    finally:
        progress.finish()
    print(f"Inventaire : {rep.listed} fichiers ({rep.new} nouveaux, {rep.changed} modifiés, "
          f"{rep.moved} déplacés ou renommés, {rep.gone} disparus)")
    from .decisions import scope_counts
    to_decide = scope_counts(conn, args.root).get("a_decider", 0)
    if to_decide:
        print(f"{to_decide} fichiers dans des dossiers à décider, non analysés : penny dossiers \"{args.root}\"")
    if rep.unreadable:
        print(f"Attention : {rep.unreadable} fichiers ou dossiers illisibles par penny (non comptés comme "
              "disparus) — voir penny onedrive check")
    print(f"Ce passage : {rep.processed} analysés, {rep.no_text} sans texte, {rep.skipped} ignorés, "
          f"{rep.errors} en erreur" + (f" {rep.error_codes}" if rep.error_codes else ""))
    print(f"Reste à traiter : {rep.remaining}" + (" — relancer la même commande pour continuer" if rep.remaining else ""))


class _Quit(Exception):
    pass


CHOICES = {"a": "analyser", "i": "inventaire", "x": "ignorer"}


def _ask(prompt: str, allowed: str, default: str | None = None) -> str:
    """Entrée seule = réponse par défaut (affichée en majuscule dans la question)."""
    while True:
        answer = input(prompt).strip().lower()[:1]
        if not answer and default:
            return default
        if answer in allowed:
            return answer
        print(f"  Réponse attendue : {', '.join(allowed)}")


def _review(conn, decisions, root: str, parent: str, export, revoir: bool) -> None:
    from .decisions import A_DECIDER, LABELS, folder_stats, human_size, norm
    subs, loose = folder_stats(conn, root, parent)
    title = parent or "(dossier entier)"
    print(f"\n« {title} »")
    print(f"  {'N°':>3}  {'Sous-dossier':<34} {'Fichiers':>8} {'Taille':>9}  {'Types principaux':<28} {'Récent':<8} Décision")
    for n, s in enumerate(subs, 1):
        explicit = decisions.full.get(norm(s["folder"]))
        effective = decisions.for_folder(s["folder"])
        shown = LABELS[effective] + ("" if explicit or effective == A_DECIDER else " (hérité)")
        print(f"  {n:>3}  {s['name'][:34]:<34} {s['files']:>8} {human_size(s['size']):>9}  "
              f"{s['types'][:28]:<28} {s['latest']:<8} {shown}")
    if loose["files"]:
        print(f"  {'':>3}  {'(fichiers posés ici)':<34} {loose['files']:>8} {human_size(loose['size']):>9}  "
              f"{loose['types'][:28]:<28} {loose['latest']:<8} {LABELS[decisions.for_file(f'{parent}/x' if parent else 'x')]}")
    for n, s in enumerate(subs, 1):
        if not revoir and decisions.for_folder(s["folder"]) != A_DECIDER:
            continue
        c = _ask(f"Dossier {n} « {s['name']} » ({s['files']} fichiers) : [A]nalyser (Entrée), [i]nventaire seul, "
                 "[x] ignorer, [d]écider ses sous-dossiers, [p]lus tard, [q]uitter ? ", "aixdpq", default="a")
        if c == "q":
            raise _Quit
        if c in CHOICES:
            decisions.set(s["folder"], CHOICES[c])
            export()
        elif c == "d":
            _review(conn, decisions, root, s["folder"], export, revoir)
    loose_key = f"{parent}/x" if parent else "x"
    if loose["files"] and (revoir or decisions.for_file(loose_key) == A_DECIDER):
        c = _ask(f"Les {loose['files']} fichiers posés directement dans « {title} » : [A]nalyser (Entrée), "
                 "[i]nventaire seul, [x] ignorer, [p]lus tard, [q]uitter ? ", "aixpq", default="a")
        if c == "q":
            raise _Quit
        if c in CHOICES:
            decisions.set(parent, CHOICES[c], files_only=True)
            export()


def cmd_dossiers(cfg: Config, args) -> None:
    """Décider, dossier par dossier, ce que Penny peut analyser. Rien n'est lu pour décider :
    les chiffres affichés viennent du seul inventaire (noms, tailles, dates)."""
    from .decisions import LABELS, Decisions, apply_scope, export_markdown, norm
    conn = db.connect(cfg.db_path)
    export_path = cfg.data_dir / "decisions" / "dossiers.md"
    decisions = Decisions(conn, args.root)

    def export() -> None:
        apply_scope(conn, args.root, decisions)
        export_markdown(conn, export_path)

    if args.decider:
        folder, choice = args.decider
        choice = {"annuler": None, "analyser": "analyser", "inventaire": "inventaire", "ignorer": "ignorer"}.get(choice, "?")
        if choice == "?":
            sys.exit("Décision attendue : analyser, inventaire, ignorer ou annuler")
        decisions.set(folder, choice, files_only=args.fichiers_seulement)
        export()
        print(f"« {norm(folder) or '(dossier entier)'} » : {LABELS[choice] if choice else 'décision annulée'}")
        return
    if args.liste:
        rows = conn.execute("SELECT folder, files_only, decision, decided_at FROM folder_decisions WHERE root = ? "
                            "ORDER BY folder", (args.root,)).fetchall()
        for r in rows:
            print(f"  {LABELS[r['decision']]:<16} {r['folder'] or '(dossier entier)'}"
                  + (" (fichiers seulement)" if r["files_only"] else "") + f"  — {r['decided_at'][:10]}")
        print(f"{len(rows)} décisions. Journal lisible : {export_path}")
        return

    print(f"Inventaire de « {args.root} » (noms, tailles, dates : rien n'est lu)…")
    scanner = Scanner(conn, _source(cfg, conn), LocalExtractor(), None, cfg.cache_dir, cfg.markdown_dir,
                      cfg.max_file_mb)
    from .pipeline import ScanReport
    scanner.inventory(args.root, ScanReport(), accept_gone=False)
    try:
        if decisions.for_folder("") == "a_decider" or args.revoir:
            c = _ask("Pour le dossier entier : [a]nalyser tout, [i]nventaire seul, [x] ignorer, "
                     "ou [D]écider sous-dossier par sous-dossier (Entrée) ? ", "aixd", default="d")
            if c in CHOICES:
                decisions.set("", CHOICES[c])
                export()
                print("Décision enregistrée. Pour affiner plus bas : penny dossiers \"<dossier>\" --revoir")
                return
        _review(conn, decisions, args.root, args.sous or "", export, args.revoir)
    except (_Quit, EOFError, KeyboardInterrupt):
        print("\nArrêt : les décisions déjà prises sont enregistrées.")
    export()
    print(f"\nJournal des décisions : {export_path}")
    print(status_text(conn, args.root))


def cmd_status(cfg: Config, args) -> None:
    print(status_text(db.connect(cfg.db_path, readonly=True), args.root))


def cmd_docs(cfg: Config, args) -> None:
    state = "error" if args.erreurs else "skipped" if args.ignores else None
    rows = cards_listing(db.connect(cfg.db_path, readonly=True), args.root, args.type, args.sans_texte, state,
                         args.ext)
    for r in rows:
        if r["state"] in ("error", "skipped", "no_text"):
            why = r["reason"] or ""
            print(f"{'':10}  {'(' + r['state'] + ')':<18} {r['root'].strip('/')}/{r['path']}")
            print(f"{'':12}{why}" + (f" : {r['detail']}" if r["state"] == "error" and r["detail"] else ""))
        elif r["doc_type"]:
            who = ", ".join(r["parties"][:3])
            print(f"{r['doc_date'] or '????-??-??'}  {r['doc_type'][:18]:<18} {r['title'] or ''}"
                  + (f" — {who}" if who else "") + f"\n            {r['root'].strip('/')}/{r['path']}")
        else:
            state = r["state"] or "en attente"
            print(f"{'':10}  {'(' + state + ')':<18} {r['root'].strip('/')}/{r['path']}")
    print(f"\n{len(rows)} fichiers.")
    by_ext: dict[str, int] = {}
    for r in rows:
        by_ext[r["ext"] or "(aucune)"] = by_ext.get(r["ext"] or "(aucune)", 0) + 1
    if len(by_ext) > 1:
        print("Par extension : " + ", ".join(f"{e} {n}" for e, n in sorted(by_ext.items(), key=lambda x: -x[1])))


def cmd_ask(cfg: Config, args) -> None:
    ans = Searcher(db.connect(cfg.db_path, readonly=True), _llm(cfg)).ask(args.question, args.root)
    print(ans.text)
    if ans.sources:
        print("\nSources :")
        for n, s in enumerate(ans.sources, 1):
            print(f"  [{n}] {s.path}" + (f" ({s.doc_date})" if s.doc_date else ""))
    print(f"\n{ans.perimeter}")


def cmd_models_check(cfg: Config, args) -> None:
    """Teste les modèles avec un texte INVENTÉ : la sortie peut être transmise à Claude."""
    import time
    from .pipeline import CARD_SCHEMA, CARD_SYSTEM
    llm = _llm(cfg)
    sample = ("Facture n° 2026-001 du 2026-03-15. Fournisseur : Société Exemple. "
              "Client : Jean Fictif. Montant : 120,00 euros TTC.")
    tests = [
        (f"vecteurs ({cfg.embed_model})", lambda: llm.embed([sample]).shape[1]),
        (f"fiche JSON ({cfg.llm_model})", lambda: llm.chat_json(
            CARD_SYSTEM, f"Nom du fichier : exemple.pdf\n\n--- Début du document ---\n{sample}\n--- Fin ---",
            CARD_SCHEMA).get("doc_type")),
        (f"réponse ({cfg.llm_model})", lambda: llm.chat("Réponds en un mot.", "Dis OK.")[:20]),
    ]
    failed = False
    for label, test in tests:
        t = time.monotonic()
        try:
            result = test()
            print(f"  ok     {label:<32} {time.monotonic() - t:5.1f} s  → {result}")
        except LLMError as exc:
            failed = True
            print(f"  ÉCHEC  {label:<32} {exc}")
    print("Modèles OK." if not failed else "Modèles en échec : voir les lignes ci-dessus.")


def cmd_diag(cfg: Config, args) -> None:
    print(diag_text(db.connect(cfg.db_path, readonly=True), cfg.llm_model, cfg.embed_model))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="penny", description="Penny — seconde mémoire locale")
    parser.add_argument("--version", action="version", version=f"penny {installed_version()}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    od = sub.add_parser("onedrive", help="accès OneDrive (lecture seule)")
    od_sub = od.add_subparsers(dest="action", required=True)
    od_sub.add_parser("connect", help="configurer l'accès (une fois)").set_defaults(func=cmd_connect)
    p = od_sub.add_parser("check", help="vérifier l'accès (et diagnostiquer un dossier)")
    p.add_argument("dossier", nargs="?", help="dossier à diagnostiquer, niveau par niveau")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("scan", help="inventorier et analyser un dossier OneDrive")
    p.add_argument("root", help="dossier OneDrive, ex. « Documents/Administratif »")
    p.add_argument("--limit", type=int, default=None, help="nombre maximal de fichiers à analyser ce passage")
    p.add_argument("--details", action="store_true",
                   help="afficher chaque document traité (chemin, résultat, durée) — pour votre écran seulement")
    p.add_argument("--confirmer-disparitions", action="store_true",
                   help="accepter qu'une grande partie des fichiers connus ait disparu")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("dossiers", help="décider quels dossiers analyser, garder en inventaire ou ignorer")
    p.add_argument("root", help="dossier OneDrive (le même que pour penny scan)")
    p.add_argument("--sous", help="commencer la revue à ce sous-dossier")
    p.add_argument("--revoir", action="store_true", help="redemander aussi les dossiers déjà décidés")
    p.add_argument("--liste", action="store_true", help="afficher les décisions enregistrées")
    p.add_argument("--decider", nargs=2, metavar=("SOUS_DOSSIER", "DECISION"),
                   help="décider sans question : analyser, inventaire, ignorer ou annuler ('' = dossier entier)")
    p.add_argument("--fichiers-seulement", action="store_true",
                   help="avec --decider : seulement les fichiers posés directement dans ce dossier")
    p.set_defaults(func=cmd_dossiers)
    p = sub.add_parser("status", help="état de l'analyse")
    p.add_argument("root", nargs="?")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("docs", help="inventaire des documents")
    p.add_argument("root", nargs="?")
    p.add_argument("--type", help="filtrer par type (facture, contrat…)")
    p.add_argument("--sans-texte", action="store_true", help="seulement les scans et photos sans texte")
    p.add_argument("--erreurs", action="store_true", help="seulement les fichiers en erreur, avec le détail")
    p.add_argument("--ignores", action="store_true", help="seulement les fichiers ignorés, avec la raison")
    p.add_argument("--ext", help="seulement cette extension, ex. .doc")
    p.set_defaults(func=cmd_docs)
    p = sub.add_parser("ask", help="poser une question")
    p.add_argument("question")
    p.add_argument("--root", help="limiter à un dossier analysé")
    p.set_defaults(func=cmd_ask)
    mo = sub.add_parser("models", help="modèles locaux (Ollama)")
    mo_sub = mo.add_subparsers(dest="action", required=True)
    mo_sub.add_parser("check", help="tester les modèles avec un texte inventé").set_defaults(func=cmd_models_check)
    sub.add_parser("diag", help="rapport ANONYMISÉ (le seul à transmettre à Claude)").set_defaults(func=cmd_diag)

    args = parser.parse_args(argv)
    _guard_account()
    cfg = load_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cfg.data_dir, 0o700)
    try:
        args.func(cfg, args)
    except (OneDriveError, LLMError, InventoryAborted) as exc:
        sys.exit(f"Erreur : {exc}")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc):
            sys.exit("Erreur : la base de Penny est occupée par une autre commande. Réessayer dans un instant.")
        raise
    except KeyboardInterrupt:
        sys.exit("\nInterrompu. Relancer la même commande reprend où elle s'était arrêtée.")


if __name__ == "__main__":
    main()
