"""Merge registry/slices/*.yaml into registry/authorities.yaml.

Deterministic; re-runnable. Dedupe decisions are listed in DECISIONS.md (D7). Slice files are the research
record and are never edited by this script; corrections go in registry/overrides.yaml which is applied last.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SL = ROOT / "registry" / "slices"

# id normalisation: slice id -> canonical id
RENAME = {"publictrustee": "public_trustee", "tasirrigation": "tas_irrigation", "marinuslink": "marinus_link"}
# for duplicate ids, which slice wins (others' notes are appended)
PREFER = {"tascorp": "gbe_soc", "utas": "local_gov_other", "taswater": "local_gov_other", "public_trustee": "gbe_soc"}
ORDER = ["state_bodies", "gbe_soc", "local_gov_other"]


def main() -> int:
    slices = {n: yaml.safe_load((SL / f"{n}.yaml").read_text()) for n in ORDER}
    merged: dict[str, dict] = {}
    for n in ORDER:
        for a in slices[n]["authorities"]:
            a = dict(a)
            a["id"] = RENAME.get(a["id"], a["id"])
            if a.get("parent_id"):
                a["parent_id"] = RENAME.get(a["parent_id"], a["parent_id"])
            a.setdefault("slice", n)
            if a["id"] in merged:
                prev = merged[a["id"]]
                winner, loser = (a, prev) if PREFER.get(a["id"]) == n else (prev, a)
                # merge: fill empty fields from loser, append notes, union aliases/sources
                for k, v in loser.items():
                    if k in ("id", "slice"):
                        continue
                    if winner.get(k) in (None, "", [], "unknown", "UNCERTAIN") and v not in (None, "", []):
                        winner[k] = v
                winner["aliases"] = sorted(set(winner.get("aliases") or []) | set(loser.get("aliases") or []))
                winner["source_of_listing"] = list(dict.fromkeys((winner.get("source_of_listing") or []) + (loser.get("source_of_listing") or [])))
                winner["notes"] = (winner.get("notes") or "") + f" [merged from slice {loser['slice']}: {loser.get('notes') or ''}]"
                winner["merged_from_slices"] = sorted({winner["slice"], loser["slice"]})
                merged[a["id"]] = winner
            else:
                merged[a["id"]] = a
    # Ministers: all share DPAC's ministerial log. One source owner, the rest reference it.
    min_ids = [i for i, a in merged.items() if a["type"] == "minister" and a.get("disclosure_log_url")]
    urls = {merged[i]["disclosure_log_url"] for i in min_ids}
    if len(urls) == 1 and min_ids:
        url = urls.pop()
        merged["ministers_dpac_log"] = {
            "id": "ministers_dpac_log", "name": "Ministers (DPAC ministerial disclosure log)", "aliases": ["Ministerial disclosure log", "MPS disclosure log"],
            "type": "minister", "rti_status": "full", "rti_status_basis": "Ministers are covered by the Act (LEGAL_MODEL.md §1; evidence per minister records)",
            "portfolio_minister": None, "disclosure_log_url": url, "disclosure_log_url_evidence": merged[min_ids[0]].get("disclosure_log_url_evidence"),
            "disclosure_log_format": "unknown", "website": "https://www.dpac.tas.gov.au", "source_of_listing": ["derived: shared log of minister records"],
            "last_verified": None, "verification_status": "network_blocked_search_only", "active": True, "tier": 1,
            "notes": "Synthetic owner record for the single DPAC-hosted ministerial disclosure log. Items are attributed to individual ministers by the adapter where the entry names the Minister.",
        }
        for i in min_ids:
            merged[i]["shares_source_with"] = "ministers_dpac_log"
    # overrides
    ov = ROOT / "registry" / "overrides.yaml"
    if ov.exists():
        for a in (yaml.safe_load(ov.read_text()) or {}).get("authorities", []):
            if a["id"] in merged:
                merged[a["id"]].update({k: v for k, v in a.items() if k not in ("id", "notes_override")})
                if a.get("notes_override"):
                    merged[a["id"]]["notes"] = a["notes_override"] + " [original: " + (merged[a["id"]].get("notes") or "")[:300] + "]"
            else:
                merged[a["id"]] = {k: v for k, v in a.items() if k != "notes_override"}
    out = {
        "generated_by": "scripts/merge_registry.py",
        "sources": [f"registry/slices/{n}.yaml" for n in ORDER] + ["registry/overrides.yaml"],
        "authorities": [merged[i] for i in sorted(merged)],
        "minister_portfolios": slices["state_bodies"].get("minister_portfolios", []),
        "mog_changes": slices["state_bodies"].get("mog_changes", []),
        "name_history": [{**h, "id": RENAME.get(h["id"], h["id"])} for h in slices["gbe_soc"].get("name_history", [])],
    }
    (ROOT / "registry" / "authorities.yaml").write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=120))
    print(f"wrote {len(out['authorities'])} authorities")
    return 0


if __name__ == "__main__":
    sys.exit(main())
