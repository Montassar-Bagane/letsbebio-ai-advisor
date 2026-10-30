#!/usr/bin/env python3
"""
validate.py — expert validation harness.

Runs a fixed set of realistic customer profiles against the live API and
produces a printable review sheet in French. A beauty advisor marks each
recommended product Bon / Acceptable / Mauvais on paper.

The same profiles double as a regression test: save a baseline, change the
scoring, re-run, and see exactly what moved.

Setup:
    pip install reportlab

Usage:
    python3 validate.py                     # PDF + baseline JSON
    python3 validate.py --save-baseline     # overwrite the reference run
    python3 validate.py --compare           # diff against the baseline
    python3 validate.py --api http://...    # non-default API host

Outputs:
    validation_sheet.pdf     give this to the advisor
    validation_run.json      raw results
    validation_baseline.json reference for regression comparison
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# The profiles. Chosen to cover the catalogue's real range, including the
# thin segments — a profile that returns nothing is a finding, not a bug.
# ---------------------------------------------------------------------------

PROFILES = [
    # --- visage: the dense, commercially important cases ------------------
    {"id": "V01", "titre": "Taches post-grossesse, peau sensible",
     "contexte": "Femme 32 ans, masque de grossesse, réagit aux parfums.",
     "req": {"domain": "visage", "concerns": ["taches_pigmentaires"],
             "skin_type": "sensible"}},
    {"id": "V02", "titre": "Taches anciennes, peau mixte, soir",
     "contexte": "Femme 40 ans, taches installées depuis des années.",
     "req": {"domain": "visage", "concerns": ["taches_pigmentaires"],
             "skin_type": "mixte", "usage_time": "soir"}},
    {"id": "V03", "titre": "Acné adulte, peau grasse",
     "contexte": "Homme 26 ans, boutons persistants, brillance en journée.",
     "req": {"domain": "visage", "concerns": ["imperfections_acne"],
             "skin_type": "grasse"}},
    {"id": "V04", "titre": "Peau grasse, budget serré",
     "contexte": "Étudiante 21 ans, 60 DT maximum pour toute la routine.",
     "req": {"domain": "visage", "concerns": ["exces_sebum"],
             "skin_type": "grasse", "budget_max": 60}},
    {"id": "V05", "titre": "Rides et fermeté, peau mature",
     "contexte": "Femme 55 ans, perte de fermeté, soin du soir.",
     "req": {"domain": "visage", "concerns": ["rides_age"],
             "skin_type": "mature", "usage_time": "soir"}},
    {"id": "V06", "titre": "Peau très sèche en hiver",
     "contexte": "Femme 35 ans, tiraillements, desquamation.",
     "req": {"domain": "visage", "concerns": ["deshydratation"],
             "skin_type": "seche"}},
    {"id": "V07", "titre": "Rougeurs et sensibilité",
     "contexte": "Femme 29 ans, rougeurs diffuses, peau réactive.",
     "req": {"domain": "visage", "concerns": ["rougeurs_sensibilite"],
             "skin_type": "sensible"}},
    {"id": "V08", "titre": "Protection solaire, peau mixte",
     "contexte": "Client 30 ans, exposition quotidienne, veut du SPF.",
     "req": {"domain": "visage", "concerns": ["protection_solaire"],
             "skin_type": "mixte", "usage_time": "matin"}},
    {"id": "V09", "titre": "Teint terne, éclat",
     "contexte": "Femme 38 ans, teint fatigué, cherche de la luminosité.",
     "req": {"domain": "visage", "concerns": ["eclat_teint"]}},
    {"id": "V10", "titre": "Cernes et poches",
     "contexte": "Homme 34 ans, manque de sommeil, contour des yeux marqué.",
     "req": {"domain": "visage", "concerns": ["cernes_poches"]}},

    # --- the thin segment: expected to be weak -----------------------------
    {"id": "V11", "titre": "Peau normale, entretien simple",
     "contexte": "Femme 25 ans, aucun problème particulier. "
                 "SEGMENT MINCE au catalogue — résultat faible attendu.",
     "req": {"domain": "visage", "concerns": ["deshydratation"],
             "skin_type": "normale"}},
    {"id": "V12", "titre": "Peau mixte, imperfections légères",
     "contexte": "Femme 28 ans, zone T grasse, joues normales.",
     "req": {"domain": "visage", "concerns": ["imperfections_acne"],
             "skin_type": "mixte"}},

    # --- cheveux -----------------------------------------------------------
    {"id": "C01", "titre": "Chute de cheveux",
     "contexte": "Femme 35 ans, chute saisonnière importante.",
     "req": {"domain": "cheveux", "concerns": ["chute_cheveux"]}},
    {"id": "C02", "titre": "Pellicules et cuir chevelu gras",
     "contexte": "Homme 27 ans, pellicules récurrentes.",
     "req": {"domain": "cheveux", "concerns": ["pellicules"],
             "skin_type": "gras"}},
    {"id": "C03", "titre": "Cheveux secs et abîmés",
     "contexte": "Femme 30 ans, cheveux colorés, pointes cassantes.",
     "req": {"domain": "cheveux", "concerns": ["cheveux_abimes"],
             "skin_type": "abimes"}},
    {"id": "C04", "titre": "Cheveux bouclés déshydratés",
     "contexte": "Femme 24 ans, boucles sèches et ternes.",
     "req": {"domain": "cheveux", "concerns": ["deshydratation"],
             "skin_type": "boucles_frises"}},

    # --- corps -------------------------------------------------------------
    {"id": "B01", "titre": "Peau du corps très sèche",
     "contexte": "Femme 45 ans, sécheresse des jambes et des bras.",
     "req": {"domain": "corps", "concerns": ["deshydratation"],
             "skin_type": "seche"}},
    {"id": "B02", "titre": "Déodorant peau sensible",
     "contexte": "Femme 31 ans, irritations sous les bras.",
     "req": {"domain": "corps", "concerns": ["rougeurs_sensibilite"],
             "skin_type": "sensible"}},

    # --- compléments -------------------------------------------------------
    {"id": "I01", "titre": "Cheveux, peau et ongles",
     "contexte": "Femme 33 ans, ongles cassants, cheveux ternes.",
     "req": {"domain": "interieur", "concerns": ["cheveux_peau_ongles"]}},
    {"id": "I02", "titre": "Fatigue et manque d'énergie",
     "contexte": "Homme 40 ans, fatigue chronique en fin de journée.",
     "req": {"domain": "interieur", "concerns": ["energie_tonus"]}},
    {"id": "I03", "titre": "Digestion difficile",
     "contexte": "Femme 36 ans, ballonnements après les repas.",
     "req": {"domain": "interieur", "concerns": ["digestion"]}},
    {"id": "I04", "titre": "Sommeil et stress",
     "contexte": "Femme 42 ans, difficultés d'endormissement.",
     "req": {"domain": "interieur", "concerns": ["sommeil_stress"]}},
]

L_STEP = {"nettoyage": "Nettoyer", "tonification": "Tonifier",
          "traitement": "Traiter", "hydratation": "Hydrater",
          "protection": "Protéger", "soin_cible": "Soin ciblé",
          "complement_oral": "Complément"}
L_DOMAIN = {"visage": "Visage", "cheveux": "Cheveux",
            "corps": "Corps", "interieur": "Bien-être"}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def call(api: str, profile: dict) -> dict:
    """One request, with a polite retry if the server rate-limits us.

    The API allows 60 requests a minute. Running this script several times in
    quick succession exceeds that — which is the rate limiter working, not a
    fault. So back off and retry rather than recording a false failure.
    """
    body = json.dumps(profile["req"]).encode()
    for attempt in range(4):
        req = urllib.request.Request(
            api.rstrip("/") + "/recommend", data=body,
            headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                wait = 20 * (attempt + 1)
                sys.stdout.write(f"[limite atteinte, pause {wait}s] ")
                sys.stdout.flush()
                time.sleep(wait)
                continue
            return {"_error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
        except Exception as e:
            return {"_error": str(e)}
    return {"_error": "429 après plusieurs tentatives"}


def run_all(api: str, delay: float = 1.1) -> list:
    out = []
    for i, p in enumerate(PROFILES):
        sys.stdout.write(f"  {p['id']} {p['titre'][:44]:<46}")
        sys.stdout.flush()
        res = call(api, p)
        if "_error" in res:
            print("ERREUR")
        else:
            n = len(res.get("routine", []))
            m = res.get("profile", {}).get("matched_products", 0)
            print(f"{n} étapes, {m} produits")
        out.append({"profile": p, "result": res})
        if i < len(PROFILES) - 1:
            time.sleep(delay)          # stay under 60 requests/minute
    return out


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def build_pdf(runs: list, path: str, api: str) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    INK = colors.HexColor("#14231C")
    LEAF = colors.HexColor("#2E6B4F")
    ROSE = colors.HexColor("#A63D57")
    MUTED = colors.HexColor("#5C7167")
    LINE = colors.HexColor("#CFD9CD")

    ss = getSampleStyleSheet()
    st = {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold",
                                fontSize=19, textColor=INK, alignment=0, spaceAfter=4),
        "sub": ParagraphStyle("s", parent=ss["Normal"], fontSize=9.5,
                              textColor=MUTED, spaceAfter=3),
        "h": ParagraphStyle("h", parent=ss["Normal"], fontName="Helvetica-Bold",
                            fontSize=12.5, textColor=INK, spaceBefore=10, spaceAfter=2),
        "ctx": ParagraphStyle("c", parent=ss["Normal"], fontSize=9,
                              textColor=MUTED, spaceAfter=6, leading=12),
        "body": ParagraphStyle("b", parent=ss["Normal"], fontSize=9, leading=12),
        "small": ParagraphStyle("sm", parent=ss["Normal"], fontSize=7.5,
                                textColor=MUTED, leading=9.5),
        "warn": ParagraphStyle("w", parent=ss["Normal"], fontSize=9,
                               textColor=ROSE, spaceAfter=6),
    }

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Validation des recommandations")
    story = []

    # --- cover ------------------------------------------------------------
    story += [
        Paragraph("Validation des recommandations", st["title"]),
        Paragraph(f"Moteur de recommandation · {date.today().isoformat()}", st["sub"]),
        Spacer(1, 8 * mm),
        Paragraph("Comment remplir ce document", st["h"]),
        Paragraph(
            "Chaque page présente un profil client réel et la routine proposée par "
            "le moteur. Pour <b>chaque produit</b>, cochez une case :", st["body"]),
        Spacer(1, 3 * mm),
    ]

    legend = Table([
        ["BON", "Le produit convient à ce profil. Je le recommanderais moi-même."],
        ["ACCEPT.", "Le produit n'est pas faux, mais ce n'est pas mon premier choix."],
        ["MAUVAIS", "Le produit ne convient pas, ou pourrait poser problème."],
    ], colWidths=[22 * mm, 150 * mm])
    legend.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8),
        ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, 0), LEAF),
        ("TEXTCOLOR", (0, 2), (0, 2), ROSE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [legend, Spacer(1, 5 * mm)]

    story += [
        Paragraph(
            "<b>L'objectif est zéro « mauvais ».</b> En conseil beauté, un produit "
            "inadapté n'est pas une erreur de classement : c'est une perte de "
            "confiance du client. Un « acceptable » se corrige, un « mauvais » doit "
            "être compris avant la mise en ligne.", st["body"]),
        Spacer(1, 4 * mm),
        Paragraph(
            "Si une étape manque (par exemple aucune protection solaire), notez-le "
            "dans les commentaires : cela indique un manque au catalogue, pas "
            "forcément un défaut du moteur.", st["body"]),
        Spacer(1, 8 * mm),
    ]

    ok = sum(1 for r in runs if "_error" not in r["result"])
    empty = sum(1 for r in runs if "_error" not in r["result"]
                and not r["result"].get("routine"))
    summary = Table([
        ["Profils testés", str(len(runs))],
        ["Profils avec une routine", str(ok - empty)],
        ["Profils sans routine", str(empty)],
        ["Erreurs techniques", str(len(runs) - ok)],
        ["API", api],
    ], colWidths=[55 * mm, 117 * mm])
    summary.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [Paragraph("Résumé de cette campagne", st["h"]), summary, PageBreak()]

    # --- one block per profile -------------------------------------------
    def check_row(label: str, name: str, brand: str, price: str, why: str):
        return [
            Paragraph(f"<b>{label}</b>", st["small"]),
            Paragraph(f"<b>{name}</b><br/>"
                      f'<font size="7.5" color="#5C7167">{brand or "—"} · {price}'
                      f'{(" · " + why) if why else ""}</font>', st["body"]),
            "", "", "",
        ]

    for i, r in enumerate(runs):
        p, res = r["profile"], r["result"]
        block = [
            Paragraph(f"{p['id']} — {p['titre']}", st["h"]),
            Paragraph(p["contexte"], st["ctx"]),
        ]

        req = p["req"]
        crit = [L_DOMAIN.get(req["domain"], req["domain"])]
        crit += req.get("concerns", [])
        if req.get("skin_type"):
            crit.append("type : " + req["skin_type"])
        if req.get("usage_time"):
            crit.append(req["usage_time"])
        if req.get("budget_max"):
            crit.append(f"budget {req['budget_max']} DT")
        block.append(Paragraph("Critères : " + " · ".join(crit), st["small"]))
        block.append(Spacer(1, 3 * mm))

        if "_error" in res:
            block.append(Paragraph("ERREUR TECHNIQUE : " + res["_error"], st["warn"]))
            story += [KeepTogether(block), Spacer(1, 6 * mm)]
            continue

        routine = res.get("routine", [])
        matched = res.get("profile", {}).get("matched_products", 0)

        if not routine:
            block.append(Paragraph(
                f"Aucune routine proposée ({matched} produits correspondants). "
                "Manque probable au catalogue — à confirmer.", st["warn"]))
        else:
            rows = [["Étape", "Produit", "Bon", "Accept.", "Mauvais"]]
            for step in routine:
                pr = step["product"]
                price = (f"{pr['price']} DT" if pr.get("price") else "prix n/c")
                if pr.get("in_stock") is False:
                    price += " · RUPTURE"
                rows.append(check_row(
                    L_STEP.get(step["step"], step["step"]),
                    pr.get("name", ""), pr.get("brand", ""), price,
                    step.get("reason", "")))

            t = Table(rows, colWidths=[20 * mm, 106 * mm, 15 * mm, 16 * mm, 17 * mm])
            t.setStyle(TableStyle([
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (2, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 1), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
                # the boxes to tick
                ("BOX", (2, 1), (2, -1), 0.5, LEAF),
                ("BOX", (3, 1), (3, -1), 0.5, MUTED),
                ("BOX", (4, 1), (4, -1), 0.5, ROSE),
                ("INNERGRID", (2, 1), (-1, -1), 0.5, LINE),
            ]))
            block += [t, Spacer(1, 2 * mm),
                      Paragraph(f"{matched} produits correspondants au total.",
                                st["small"])]

            packs = res.get("packs", [])
            if packs:
                names = ", ".join(x.get("name", "") for x in packs[:3])
                block.append(Paragraph(f"Packs proposés : {names}", st["small"]))

        block += [
            Spacer(1, 3 * mm),
            Paragraph("Commentaire (produit manquant, meilleure alternative, "
                      "contre-indication) :", st["small"]),
        ]
        note = Table([[""]], colWidths=[174 * mm], rowHeights=[16 * mm])
        note.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, LINE)]))
        block.append(note)

        story.append(KeepTogether(block))
        story.append(Spacer(1, 7 * mm))
        if i % 2 == 1 and i != len(runs) - 1:
            story.append(PageBreak())

    # --- closing ----------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("Questions générales", st["h"]),
        Paragraph("À remplir après avoir parcouru tous les profils.", st["sub"]),
        Spacer(1, 4 * mm),
    ]
    for q in [
        "Y a-t-il des produits qui ne devraient jamais être recommandés "
        "ensemble (incompatibilités) ?",
        "Manque-t-il des étapes que vous jugez indispensables dans une routine ?",
        "Certaines préoccupations devraient-elles renvoyer vers un complément "
        "alimentaire en plus des soins ?",
        "Y a-t-il des profils clients fréquents en boutique qui ne figurent pas "
        "dans cette liste ?",
        "Pour les packs de la marque : quelle est la composition exacte de chacun ?",
    ]:
        story.append(Paragraph(q, st["body"]))
        box = Table([[""]], colWidths=[174 * mm], rowHeights=[20 * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, LINE)]))
        story += [Spacer(1, 2 * mm), box, Spacer(1, 5 * mm)]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 10 * mm, "Validation des recommandations")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


# ---------------------------------------------------------------------------
# regression comparison
# ---------------------------------------------------------------------------

def ids_of(res: dict) -> list:
    return [s["product"]["id"] for s in res.get("routine", [])]


def compare(runs: list, baseline_path: Path) -> None:
    if not baseline_path.exists():
        sys.exit(f"{baseline_path} introuvable — lancez d'abord --save-baseline.")
    base = {r["profile"]["id"]: r for r in json.loads(
        baseline_path.read_text(encoding="utf-8"))}

    changed = same = 0
    print("\nComparaison avec la référence\n" + "=" * 60)
    for r in runs:
        pid = r["profile"]["id"]
        old = ids_of(base.get(pid, {}).get("result", {}))
        new = ids_of(r["result"])
        if old == new:
            same += 1
            continue
        changed += 1
        print(f"\n{pid} — {r['profile']['titre']}")
        names = {s["product"]["id"]: s["product"]["name"]
                 for s in r["result"].get("routine", [])}
        for i in set(old) - set(new):
            print(f"   retiré  {i}")
        for i in set(new) - set(old):
            print(f"   ajouté  {i}  {names.get(i, '')[:52]}")
        if set(old) == set(new):
            print("   (ordre modifié seulement)")

    print("\n" + "=" * 60)
    print(f"Identiques : {same}   Modifiés : {changed}")
    if changed:
        print("Revérifiez les profils modifiés avant de déployer.")


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--delay", type=float, default=1.1,
                    help="pause entre les requêtes (secondes)")
    args = ap.parse_args()

    print(f"API : {args.api}\n{len(PROFILES)} profils "
          f"(~{int(len(PROFILES) * args.delay)}s)\n")
    runs = run_all(args.api, args.delay)

    Path("validation_run.json").write_text(
        json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")

    errors = [r for r in runs if "_error" in r["result"]]
    if errors:
        print(f"\n{len(errors)} erreur(s). L'API tourne-t-elle ?")
        print("   " + errors[0]["result"]["_error"][:150])

    baseline = Path("baseline.json")
    if args.save_baseline:
        baseline.write_text(json.dumps(runs, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\nRéférence enregistrée : {baseline}")
    elif args.compare:
        compare(runs, baseline)
        return

    if not args.no_pdf:
        try:
            build_pdf(runs, "review_sheet.pdf", args.api)
            print("\nreview_sheet.pdf — à imprimer pour la conseillère.")
        except ImportError:
            print("\nreportlab manquant : pip install reportlab")

    empty = [r["profile"]["id"] for r in runs
             if "_error" not in r["result"] and not r["result"].get("routine")]
    if empty:
        print(f"\nProfils sans routine : {', '.join(empty)}")
        print("Ce sont des manques au catalogue — à signaler au client.")


if __name__ == "__main__":
    main()
