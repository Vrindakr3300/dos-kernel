"""The labeled citation set for the legalcite benchmark (docs/279 §4).

Each entry is a (cite, claimed_name, quoted_holding[, note]) tuple. The labels:

  REAL_CITES       — citations that DO exist in a third-party reporter, with the
                     correct case name. A sound witness must NOT flag these
                     (false-fire). Ground truth confirmed against CourtListener via the
                     name-search path (snapshot.py), so each real cite's cluster is a
                     byte Free Law Project authored.
  FABRICATED_CITES — citations a sanctioned/known-bad filing CLAIMED but that do not
                     exist AS CLAIMED. A sound witness MUST flag these (detect). Two
                     flavours:
                       (a) NO reporter carries the cite at all (pure invention), and
                       (b) the cite resolves to a DIFFERENT real case (the docs/279 §3
                           collision — a fabricated name on a real reporter slot).

Provenance of the fabrications (the unforgeable, documented part):
  * The *Mata v. Avianca* (S.D.N.Y. 2023, $5,000 sanction) fabrications are taken from
    the court's own order and the contemporaneous reporting (June-2026 web check):
    Varghese v. China Southern (925 F.3d 1339), Zaunbrecher v. Transocean
    (772 F.3d 1278), Hyatt v. N. Cent. Airlines (92 F.3d 1074), Shaboon, Petersen,
    Martinez, Durden, Miller. These are the canonical, documented hallucinated cites.
  * SYNTHESIZED perturbations: real cites with the volume or page nudged by a few
    digits (a plausible-looking but non-existent neighbour), to enlarge the fabricated
    denominator beyond the eight documented Mata cites. Each is labeled `synth`.

The real cites are deliberately landmark cases (high confidence they exist + are in the
corpus) so a MISS is unambiguously a corpus/matching gap, not an obscure-case artifact
— the cheap-kill is then clean (docs/277 §6).
"""
from __future__ import annotations

# (cite, claimed_name, quoted_holding) — the quote is a real, short holding fragment
# where one is easy to state; "" where we only check existence + name.
REAL_CITES: list[tuple[str, str, str]] = [
    ("576 U.S. 644", "Obergefell v. Hodges",
     "requires a State to license a marriage between two people of the same sex"),
    ("539 U.S. 558", "Lawrence v. Texas", ""),
    ("384 U.S. 436", "Miranda v. Arizona", ""),
    ("163 U.S. 537", "Plessy v. Ferguson", ""),
    ("5 U.S. 137", "Marbury v. Madison", ""),
    ("347 U.S. 483", "Brown v. Board of Education", ""),
    ("410 U.S. 113", "Roe v. Wade", ""),
    ("531 U.S. 98", "Bush v. Gore", ""),
    ("558 U.S. 310", "Citizens United v. FEC", ""),
    ("567 U.S. 519", "NFIB v. Sebelius", ""),
]

# (cite, claimed_name, quoted_holding, note) — note records the provenance.
FABRICATED_CITES: list[tuple[str, str, str, str]] = [
    # --- The documented Mata v. Avianca fabrications (court order + reporting) ---
    ("925 F.3d 1339", "Varghese v. China Southern Airlines Co., Ltd.", "",
     "mata: the lead fabricated case, cited to the 11th Cir."),
    ("772 F.3d 1278", "Zaunbrecher v. Transocean Offshore Deepwater Drilling, Inc.", "",
     "mata: documented non-existent 11th Cir. cite"),
    ("92 F.3d 1074", "Hyatt v. N. Cent. Airlines", "",
     "mata: documented; the SLOT is real (resolves to a different case) — collision"),
    ("556 F.2d 713", "Gen. Wire Spring Co. v. O'Neal Steel, Inc.", "",
     "mata: court noted this 5th Cir. cite as not existing as claimed"),
    # --- Synthesized perturbations of REAL cites (plausible non-existent neighbours) ---
    ("576 U.S. 645", "Obergefell v. Hodges", "",
     "synth: Obergefell page +1 — plausible but wrong"),
    ("539 U.S. 559", "Lawrence v. Texas", "",
     "synth: Lawrence page +1"),
    ("384 U.S. 999", "Miranda v. Arizona", "",
     "synth: Miranda page replaced"),
    ("999 U.S. 113", "Roe v. Wade", "",
     "synth: Roe volume replaced (no such U.S. volume)"),
    ("163 F.3d 537", "Plessy v. Ferguson", "",
     "synth: Plessy reporter swapped U.S.->F.3d (wrong reporter)"),
    ("5 U.S. 1370", "Marbury v. Madison", "",
     "synth: Marbury page x10"),
]
