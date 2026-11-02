"""Builders for the kssos.org race-block layout, in the markup observed live.

Captured from https://www.kssos.org/ent/kssos_ent.html (the archived August 4,
2026 primary) by `--probe-results` on a CI runner on 2026-11-02. Quoting, the
county tooltips inside <area title="...">, and the unclosed <tr> before the
first candidate row are all reproduced on purpose — they are what the parser
has to survive.
"""

from __future__ import annotations


def _statewide_row(name: str, votes: int, pct: int) -> str:
    return (
        "<div class='row'> <div class='col-6'> <p>" + name + "</p> </div> "
        "<div class='col-2'> <p>" + f"{votes:,}" + "</p> </div> "
        "<div class='col-1'> <p>" + f"{pct}%" + "</p> </div> "
        "<div class='col-3'> <table width='100%' border='0' cellspacing='0' cellpadding='0'> "
        f"<tr><td width='{pct}%' height='100%' bgcolor='#CC0000'>&nbsp;</td> "
        "<td width='68%' height='100%' >&nbsp;</td> </tr></table> </div> </div> "
        "<div class='row'> <div class='col-12 spacer'> </div> </div> "
    )


def _county_tooltip(county: str, reporting: int, total: int, rows: list[tuple[str, int]]) -> str:
    body = "".join(
        f"<tr><td style='padding-right:15px'>{label}</td>"
        f"<td style='text-align:right'>{votes:,}</td></tr> "
        for label, votes in rows
    )
    return (
        f"<area shape='poly' coords='1,2,3,4' class=\"tooltip\" href='{county.lower()}.html#top' "
        f"alt='{county}' title=\"<table style='border-collapse: collapse; border-spacing: 0;' cellpadding='0'>\n"
        f"<tr><td align='left' colspan='2'><span class='county'>{county} County</span>"
        f"<br/>{reporting} of {total} precincts reporting</td></tr>\n"
        "<tr><td>Candidate</td><td>Votes</td></tr>\n<tr><td colspan='2'><hr/></td>\n<tr>\n"
        f"{body}</table>\" /> "
    )


def race(
    heading: str,
    reporting: int,
    total: int,
    statewide: list[tuple[str, int, int]],
    counties: list[tuple[str, int, int, list[tuple[str, int]]]],
    race_id: int = 1001,
) -> str:
    total_votes = sum(v for _, v, _ in statewide)
    return (
        "<div class='race'> <div class='container-md'> <div class='row race-heading'> "
        f"<div class='col-11'> <h3>{heading}</h3> </div> "
        "<div class='col-1 favorite-race'> <label class='container'> "
        f"<input type='checkbox' name='chkbxFavoriteRace' id='{race_id}' /> "
        "<span class='checkmark'></span> </label> </div> </div><!-- end of .race-heading --> "
        "<div class='row race-subheading'> <div class='col-6'> "
        f"<p>Precincts Reporting: {reporting} of {total}</p> </div> "
        "<div class='col-2'> <p>Votes</p> </div> <div class='col-1'> <p>%</p> </div> "
        "<div class='col-3 view-details'> </div> </div><!-- end of .race-subheading --> "
        "<div class='race-candidate-list'> "
        + "".join(_statewide_row(n, v, p) for n, v, p in statewide)
        + "<div class='row'> <div class='col-12 spacer-bold'></div> "
        "<div class='col-6'> <p>Total Votes</p> </div> "
        f"<div class='col-2'> <p>{total_votes:,}</p> </div> "
        "<div class='col-1'> <p>&nbsp;</p> </div> "
        "<div class='col-3 back-to-top'> <a href='#top'>Back to Top</a> </div> </div> "
        "</div><!-- end of .race-candidate-list --> "
        "<div class='row'> <div class='col-12'> "
        f"<div class='race-details collapse' id='all-races-{race_id}'> "
        "<div class='map-image'> <img src='images/ussr_map.gif' usemap='#Map3' /> "
        "<map name='Map3' id='Map3'> "
        + "".join(_county_tooltip(c, r, t, rows) for c, r, t, rows in counties)
        + "</map> </div> "
        "<div class='race-legend-candidate-list'> <div class='row race-legend-candidate-list'> "
        "<div class='col-6'> <p><span class='canidatename'>Tie</span></p> </div> </div> </div> "
        "</div><!-- end of .race-details --> </div> </div> "
        "</div><!-- end of .container --> </div><!--end of .race --> "
    )


def page(*races: str) -> str:
    return (
        "<html><body><h1>Unofficial Kansas Election Results</h1> "
        "<p>Last Updated: 11/03/2026 9:40 PM</p> <p>COUNTIES REPORTING</p> "
        # A page-level precinct line that is NOT the Senate contest's, to prove
        # the parser reads the contest's own.
        "<p>Allen County 22 of 22 precincts reporting</p> "
        + "".join(races)
        + "</body></html>"
    )
