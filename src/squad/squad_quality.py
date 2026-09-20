#!/usr/bin/env python3
"""Squad Quality Indices for WC2026 match prediction.

Converts per-player club stats into two team-level indices:

  SAI (Squad Attack Index)   > 1.0 → stronger than average attack
  SDI (Squad Defence Index)  < 1.0 → stronger than average defence
                             > 1.0 → weaker defence (opponents score more)

Both normalized so the 48-team mean = 1.0, keeping the same scale as the
Poisson model's att / dfc parameters.

Players NOT matched in the top-11 league dataset are assigned the 20th-percentile
baseline for their position — reflecting the assumption that absence from a
major league implies below-average quality.

Attack composite  = goals_p90 + 0.4·assists_p90 + 0.1·key_passes_p90
                    (or shots_on_target_p90·0.35 + 0.1·kp if no goals data)
Defence composite = tackles_p90 + interceptions_p90   (outfield)
                  = saves_p90                          (GK)
"""
from collections import defaultdict
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[2]  # src/squad/... -> repo root
PROCESSED = ROOT / "data" / "processed"

# ------------------------------------------------------------------ weights --

# How much each position contributes to team attack / defence
ATK_WEIGHT = {"FWD": 2.0, "MID": 1.0, "DEF": 0.2, "GK": 0.0}
DEF_WEIGHT = {"GK":  2.0, "DEF": 1.5, "MID": 0.8, "FWD": 0.0}

# 20th-percentile replacement levels per position, derived from the 11-league dataset.
# Players not in the dataset get these values — consistently below-average.
_REPL = {
    "FWD": {"atk": 0.306, "def": 0.529},   # sot_p20*0.35 + kp_p20*0.1 ; tkl+int p20
    "MID": {"atk": 0.118, "def": 1.282},
    "DEF": {"atk": 0.030, "def": 1.667},
    "GK":  {"atk": 0.000, "def": 2.400},   # saves_p90 p20
}

MIN_MINUTES = 450  # minimum club minutes to trust the stats


# ----------------------------------------------------------------- helpers --

def _f(val, default=0.0):
    """Safe float conversion."""
    try:
        return float(val) if val not in (None, "", "nan") else default
    except (ValueError, TypeError):
        return default


def _atk(row, pos):
    """Attack composite for a matched club-stats row."""
    g90 = _f(row.get("goals_p90"))
    sot = _f(row.get("shots_on_target_p90"))
    a90 = _f(row.get("assists_p90"))
    kp  = _f(row.get("key_passes_p90"))
    if g90 > 0:
        return g90 + 0.4 * a90 + 0.1 * kp
    # no goals data: use shots as proxy (league-avg conversion ~35%)
    return sot * 0.35 + 0.1 * kp


def _def(row, pos):
    """Defence composite for a matched club-stats row."""
    if pos == "GK":
        return _f(row.get("saves_p90"))
    return _f(row.get("tackles_p90")) + _f(row.get("interceptions_p90"))


def _load_pstart():
    """Return {player_id (str): p_start} from player_projections.csv."""
    import csv
    out = {}
    path = PROCESSED / "player_projections.csv"
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out[str(row["player_id"])] = _f(row.get("p_start"), 0.10)
    return out


# --- live World Cup form (data/processed/wc_player_form.csv) ----------------
# Weight given to actual tournament output when blending into the attack
# composite. Tournament samples are tiny (≤3 games) and noisy, but they are
# the most relevant signal for who is producing *now*, so a moderate weight.
WC_BLEND_W = 0.45
WC_MIN_MINUTES = 90


def _name_key(first, last):
    """(first-initial, normalised-surname) — disambiguates shared surnames."""
    import unicodedata
    def n(s):
        s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
        return s.lower().strip()
    fi = (n(first)[:1] or "?")
    return (fi, n(last))


def _load_wc_form():
    """{(initial, surname): {goals_p90, assists_p90, mins}} from WC form table."""
    import csv
    out = {}
    path = PROCESSED / "wc_player_form.csv"
    if not path.exists():
        return out
    with open(path) as fh:
        for r in csv.DictReader(fh):
            # short name like "L. Messi" or single token "Alisson"
            name = r["name"].strip()
            if "." in name:
                ini, surname = name.split(".", 1)
                key = _name_key(ini, surname)
            else:
                key = _name_key("", name)
            prev = out.get(key)
            if prev is None or int(r["mins"]) > prev["mins"]:
                out[key] = {"goals_p90": _f(r["goals_p90"]),
                            "assists_p90": _f(r["assists_p90"]),
                            "mins": int(r["mins"])}
    return out


def _wc_atk(form):
    """Attack composite from live tournament per-90s."""
    return form["goals_p90"] + 0.4 * form["assists_p90"]


# ------------------------------------------------------------------- main ---

def compute_squad_indices(players, xwalk, club):
    """
    Parameters
    ----------
    players : list of player dicts from load_players() (status == 'playing')
    xwalk   : {player_id: {club_player_id, ...}}  (load_player_crosswalk())
    club    : {club_player_id: stat_row}           (built from load_club_stats())

    Returns
    -------
    {squad_id: {"attack": SAI, "defence": SDI}}
        SAI > 1 → above-average attack
        SDI < 1 → above-average defence (opponents score less)
        SAI = SDI = 1.0 → exactly average
    """
    p_start = _load_pstart()
    wc_form = _load_wc_form()

    atk_num = defaultdict(float)
    atk_den = defaultdict(float)
    def_num = defaultdict(float)
    def_den = defaultdict(float)

    for p in players:
        pid = str(p["id"])
        sid = p["squadId"]
        pos = p["position"]
        if pos not in ATK_WEIGHT:
            continue

        ps  = p_start.get(pid, 0.10)
        xw  = xwalk.get(p["id"], {})
        cid = xw.get("club_player_id")
        row = club.get(cid) if cid else None

        if row and _f(row.get("minutes")) >= MIN_MINUTES:
            atk_val = _atk(row, pos)
            def_val = _def(row, pos)
        else:
            atk_val = _REPL[pos]["atk"]
            def_val = _REPL[pos]["def"]

        # Blend in live World Cup output (joined by name) for outfield players
        form = wc_form.get(_name_key(p.get("firstName"), p.get("lastName")))
        if form and form["mins"] >= WC_MIN_MINUTES and pos != "GK":
            atk_val = (1 - WC_BLEND_W) * atk_val + WC_BLEND_W * _wc_atk(form)

        aw = ATK_WEIGHT[pos]
        dw = DEF_WEIGHT[pos]

        atk_num[sid] += atk_val * ps * aw
        atk_den[sid] += ps * aw
        def_num[sid] += def_val * ps * dw
        def_den[sid] += ps * dw

    # Weighted-average raw scores per team
    raw_atk = {sid: atk_num[sid] / atk_den[sid] for sid in atk_den if atk_den[sid] > 0}
    raw_def = {sid: def_num[sid] / def_den[sid] for sid in def_den if def_den[sid] > 0}

    # Normalize: mean across all 48 teams = 1.0
    mean_atk = sum(raw_atk.values()) / len(raw_atk) if raw_atk else 1.0
    mean_def = sum(raw_def.values()) / len(raw_def) if raw_def else 1.0

    sai = {sid: v / mean_atk for sid, v in raw_atk.items()}
    # SDI inverted: better defence → lower value → opponents score less
    sdi = {sid: mean_def / v  for sid, v in raw_def.items()}

    all_sids = set(sai) | set(sdi)
    return {sid: {"attack": sai.get(sid, 1.0), "defence": sdi.get(sid, 1.0)}
            for sid in all_sids}


def print_squad_rankings(indices, xwalk_teams):
    """Print a diagnostic table of team SAI / SDI rankings."""
    name_of = {sid: t["name"] for sid, t in xwalk_teams.items()}
    rows = sorted(indices.items(), key=lambda x: -x[1]["attack"])
    print(f"\n{'Rank':>4}  {'Team':<26} {'SAI':>6} {'SDI':>6}  {'Quality (atk/def ratio)':>6}")
    print("-" * 60)
    for i, (sid, idx) in enumerate(rows, 1):
        name = name_of.get(sid, str(sid))
        ratio = idx["attack"] / idx["defence"] if idx["defence"] else 0
        print(f"{i:>4}  {name:<26} {idx['attack']:>6.3f} {idx['defence']:>6.3f}  {ratio:>6.3f}")
