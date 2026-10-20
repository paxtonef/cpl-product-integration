"""Operator command for conservation (run on the server, in the service's
environment; never over the web).

  python -m product_integration.conservation.cli purge                simulation (default): counts only
  python -m product_integration.conservation.cli purge --executer     execution (explicit policy required)
  python -m product_integration.conservation.cli sauvegardes [--executer]
        expired backups of deploy/sauvegarder.sh under SAUVEGARDES_DIR and media
        directories set aside by deploy/restaurer.sh; simulation by default
  python -m product_integration.conservation.cli controle             readiness of the policy (code 1 if incomplete)
  python -m product_integration.conservation.cli apres-restauration   after deploy/restaurer.sh: revokes every
        web session, then executes the purge (refused without a policy)

Output: categories and numbers only, never a plate, a VIN, a login or a path
of a medium. On an error, only the error's class is printed (its message may
carry values). Codes: 0 done, 1 interrupted, 2 refused or misconfigured.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from app.db.engine import session_scope

from product_integration.conservation import purge, sauvegardes
from product_integration.conservation.policy import ALL, BACKUPS, CASES, IDENTIFIERS, PolicyError, read_policy

RESTORE_LOCK = "RESTAURATION_A_PURGER"


def _print_interrupted(exc: BaseException) -> int:
    print(f"Purge interrompue ({type(exc).__name__}) : le lot en cours est annulé, les lots précédents sont "
          f"conservés ; relancer la même commande reprend le reste.", file=sys.stderr)
    return 1


def _purge(args) -> int:
    if not args.executer:
        print(purge.simulate().render())
        return 0
    try:
        report = purge.execute(batch_size=args.lot)
    except purge.PurgeRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — class only, the message may carry values
        return _print_interrupted(exc)
    print(report.render())
    return 0


def _backups(args) -> int:
    setting = read_policy()[BACKUPS.key]
    root = Path(args.racine) if args.racine else (Path(os.environ["SAUVEGARDES_DIR"])
                                                  if os.environ.get("SAUVEGARDES_DIR") else None)
    media_dir = Path(os.environ["PI05_MEDIA_STORAGE_DIR"]) if os.environ.get("PI05_MEDIA_STORAGE_DIR") else None
    if root is None and media_dir is None:
        print("SAUVEGARDES_DIR (ou --racine) et PI05_MEDIA_STORAGE_DIR absents : rien à examiner", file=sys.stderr)
        return 2
    found = sauvegardes.inventory(root, media_dir)
    recognised = [f for f in found if f.recognised]
    head = "Sauvegardes — exécution" if args.executer else "Sauvegardes — simulation (rien n'est modifié)"
    print(f"{head}\n- politique : {setting.describe()}\n- reconnues : {len(recognised)} ; "
          f"non reconnues (jamais supprimées) : {len(found) - len(recognised)}")
    for f in found:
        if not f.recognised:
            print(f"  non reconnue : {f.path.name} ({f.reason})")
    if not setting.defined:
        print(f"- {purge.NO_POLICY}")
        if args.executer:
            print(f"Exécution refusée, rien n'est supprimé : {BACKUPS.env} non définie", file=sys.stderr)
            return 2
        return 0
    if setting.unlimited:
        print("- rien ne serait supprimé" if not args.executer else "- rien supprimé")
        return 0
    expired = sauvegardes.due(found, datetime.now(timezone.utc) - timedelta(days=setting.days))
    if not args.executer:
        print(f"- échues : {len(expired)} seraient supprimées")
        return 0
    deleted = 0
    for item in expired:
        try:
            sauvegardes.delete(item)
        except Exception as exc:  # noqa: BLE001
            print(f"Arrêt ({type(exc).__name__}) sur {item.path.name} : {deleted} supprimée(s) avant ; "
                  f"les autres sont conservées.", file=sys.stderr)
            return 1
        deleted += 1
    print(f"- échues supprimées : {deleted}")
    return 0


def readiness(environ=None) -> tuple[bool, list[str]]:
    environ = os.environ if environ is None else environ
    lines, complete = [], True
    try:
        policy = read_policy(environ)
    except PolicyError as exc:
        return False, [str(exc)]
    for category in ALL:
        setting = policy[category.key]
        lines.append(f"{category.env} ({category.label}) : {setting.describe()}")
        if not setting.defined:
            complete = False
    if policy[CASES.key].days is not None:
        lines.append(f"{CASES.env} : les dossiers échus sont supprimés avec leurs données propres, sans retour "
                     f"possible (hors sauvegardes antérieures) ; voir le guide §9")
    if policy[IDENTIFIERS.key].days is not None:
        lines.append("limite : les artefacts vir_resolution enregistrés avant REQ-B6-091 gardent plaque et VIN "
                     "jusqu'à l'expurgation par la commande CPL (simulation par défaut) ; voir le guide §9.3")
    if not environ.get("VIR_RETENTION_DAYS", "").strip():
        complete = False
        lines.append("VIR_RETENTION_DAYS (stockage VIR, réglage propre à VIR) : non défini")
    montage = environ.get("MONTAGE_DIR")
    if montage and (Path(montage) / RESTORE_LOCK).exists():
        complete = False
        lines.append(f"{RESTORE_LOCK} présent : restauration sans purge, service à ne pas relancer")
    return complete, lines


def _controle(_args) -> int:
    complete, lines = readiness()
    print("Contrôle de préparation — conservation : " + ("complet" if complete else "INCOMPLET"))
    for line in lines:
        print(f"- {line}")
    return 0 if complete else 1


def _after_restore(args) -> int:
    reasons = purge.refusal_reasons(read_policy())
    if reasons:
        print("Après restauration : purge refusée, rien n'est supprimé : " + " ; ".join(reasons)
              + f". Le service reste fermé ({RESTORE_LOCK}).", file=sys.stderr)
        return 2
    with session_scope() as session:
        revoked = session.execute(text("DELETE FROM pi_auth.web_sessions")).rowcount
        session.commit()
    print(f"Sessions web révoquées : {revoked}")
    try:
        report = purge.execute(trigger="after_restore", batch_size=args.lot)
    except purge.PurgeRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        return _print_interrupted(exc)
    print(report.render())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="product_integration.conservation.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("purge")
    p.add_argument("--executer", action="store_true")
    p.add_argument("--lot", type=int, default=purge.DEFAULT_BATCH)
    b = sub.add_parser("sauvegardes")
    b.add_argument("--executer", action="store_true")
    b.add_argument("--racine")
    sub.add_parser("controle")
    a = sub.add_parser("apres-restauration")
    a.add_argument("--lot", type=int, default=purge.DEFAULT_BATCH)
    args = parser.parse_args(argv)
    try:
        return {"purge": _purge, "sauvegardes": _backups, "controle": _controle,
                "apres-restauration": _after_restore}[args.command](args)
    except PolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
