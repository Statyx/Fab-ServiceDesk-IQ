#!/usr/bin/env python3
"""Point d'entree anti-fuite du depot : scanner canonique + regles locales.

Ce depot est PUBLIC. La detection se fait par FORME, jamais par NOM : aucune
liste de clients n'est ecrite ici. Deux etages :

1. ``scripts/check_no_client_leak.py`` - copie **octet pour octet** du scanner
   canonique de ``Statyx/Fab-Analyze-Data-Agent`` (GUID reel, endpoint Fabric,
   chemin personnel). Ce fichier n'est jamais modifie : ce qui lui manque est
   reconfigure ici, depuis l'exterieur.
2. Une regle "nom de client" alimentee par un secret, donc absente du depot.

Denylist (facultative) :
    - variable d'environnement ``CLIENT_DENYLIST`` (une entree par ligne),
      alimentee en CI par ``${{ secrets.CLIENT_DENYLIST }}`` ;
    - a defaut, un fichier local ``.clientdeny`` a la racine (gitignore).
    - Absente : la regle est ignoree avec un avertissement, JAMAIS un echec.

Les correspondances ne sont jamais reproduites en clair dans la sortie : seuls
le fichier, la ligne et le rang de l'entree sont affiches, sans quoi les logs
publics d'Actions re-publieraient ce que ce dispositif sert a retirer.

Usage :  python scripts/check_repo_leaks.py
Code de sortie 0 = propre, 1 = fuite detectee.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

sys.path.insert(0, str(HERE))

import check_no_client_leak as canonical  # noqa: E402

DENYLIST_ENV = "CLIENT_DENYLIST"
DENYLIST_FILE = REPO_ROOT / ".clientdeny"

# Placeholders structurels volontairement commites (ids du taskflow). Le scanner
# canonique n'autorise que le GUID nul ; sa liste blanche est donc etendue ici,
# a l'execution, plutot qu'en editant le fichier canonique.
STRUCTURAL_GUID_RE = re.compile(
    r"^a1000000-0000-4000-a000-[0-9a-f]{12}$", re.IGNORECASE
)

# Un nom cite au milieu d'une palette ou d'un badge est un faux positif. Le
# contexte est reconnu par sa FORME (declaration CSS, code hexadecimal, fonction
# de couleur, URL de badge) : coder un terme de couleur pour l'exempter
# reviendrait a le publier, ce que ce dispositif sert precisement a eviter.
COLOUR_CONTEXT_RE = re.compile(
    r"color|colour|background|fill|stroke|palette|theme|border|"
    r"#[0-9a-fA-F]{3,8}|rgb\(|hsl\(|hsla\(|rgba\(|"
    r"shields\.io|badge|svg|css",
    re.IGNORECASE,
)

# re.escape protege aussi les separateurs : "zz alpha" devient "zz\ alpha". Une
# entree en deux mots doit donc tolerer espace, point, tiret, souligne ou rien.
_SEPARATOR_RE = re.compile(r"(?:\\?[\s._-])+")
_WORD_EDGE_RE = re.compile(r"\w")


def allow_structural_placeholders() -> None:
    """Tolere les GUID placeholders sans toucher au fichier canonique."""
    label = "real GUID"
    for index, (name, pattern, keep) in enumerate(canonical.CHECKS):
        if name != label:
            continue
        canonical.CHECKS[index] = (
            name,
            pattern,
            lambda match, _keep=keep: (
                _keep(match) and not STRUCTURAL_GUID_RE.match(match.group(0))
            ),
        )
        return
    raise SystemExit(
        f"check_repo_leaks: regle '{label}' introuvable dans le scanner canonique "
        "- la copie amont a change, revoir la reconfiguration."
    )


def compile_entry(entry: str) -> re.Pattern:
    """Compile une entree de denylist en motif tolerant aux separateurs."""
    body = _SEPARATOR_RE.sub(r"[\\s._-]?", re.escape(entry))
    prefix = r"\b" if _WORD_EDGE_RE.match(entry[0]) else ""
    suffix = r"\b" if _WORD_EDGE_RE.match(entry[-1]) else ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)


def parse_denylist(raw: str) -> list[re.Pattern]:
    entries = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return [compile_entry(entry) for entry in entries]


def load_denylist() -> tuple[list[re.Pattern], str]:
    raw = os.environ.get(DENYLIST_ENV, "")
    source = f"${DENYLIST_ENV}"
    if not raw.strip() and DENYLIST_FILE.is_file():
        raw = DENYLIST_FILE.read_text(encoding="utf-8")
        source = DENYLIST_FILE.name
    return parse_denylist(raw), source


def scan_denylist(patterns: list[re.Pattern]) -> list[str]:
    findings = []
    for rel_path in canonical.tracked_files():
        path = REPO_ROOT / rel_path
        if path.suffix.lower() in canonical.BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if COLOUR_CONTEXT_RE.search(line):
                continue
            for rank, pattern in enumerate(patterns, start=1):
                if pattern.search(line):
                    findings.append(
                        f"{rel_path}:{lineno}: entree de denylist no {rank}"
                    )
    return findings


def main() -> int:
    allow_structural_placeholders()
    status = canonical.main()

    patterns, source = load_denylist()
    if not patterns:
        print(
            f"::warning::denylist absente ({DENYLIST_ENV} puis {DENYLIST_FILE.name}) "
            "- regle 'nom de client' ignoree, detection par forme uniquement."
        )
        return status

    findings = scan_denylist(patterns)
    if findings:
        print(
            f"\nDenylist ({len(patterns)} entrees, source {source}) - "
            "correspondances (termes volontairement non reproduits) :\n"
        )
        for finding in findings:
            print(f"  {finding}")
        print(
            "\nRetirer la reference, ou - pour un jeton de couleur legitime - la "
            "placer sur une ligne portant un contexte de couleur explicite."
        )
        return 1

    print(f"Denylist ({len(patterns)} entrees, source {source}) : aucune correspondance.")
    return status


if __name__ == "__main__":
    sys.exit(main())
