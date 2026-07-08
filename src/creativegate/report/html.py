"""The honest HTML verdict report.

Design rationale: one clean report page is the human surface of the product.
It must show, without spin: the fused score with its band, every rung's
evidence, every validity statement (including "directional only"), all
flags, and the cheapest-next-test recommendation. An honest "unvalidated"
is rendered as prominently as a good score.
"""

from __future__ import annotations

from jinja2 import Environment, BaseLoader

from ..schemas import Verdict

_CSS = """
:root { --bg:#0f1216; --card:#171c22; --ink:#e8ebee; --dim:#98a2ad; --line:#2a323c;
        --good:#3fb97f; --warn:#e0a437; --bad:#e05c4f; --acc:#5aa7e8; }
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,'Segoe UI',Roboto,sans-serif; padding:2rem; }
.wrap { max-width:960px; margin:0 auto; }
h1 { font-size:1.35rem; margin-bottom:.25rem; }
h2 { font-size:1.02rem; margin:1.4rem 0 .6rem; color:var(--acc); }
.sub { color:var(--dim); font-size:.85rem; margin-bottom:1.4rem; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:1.1rem 1.3rem; margin-bottom:1rem; }
.scorebar { position:relative; height:14px; border-radius:7px; background:linear-gradient(90deg,#e05c4f,#e0a437,#3fb97f); margin:.9rem 0 .35rem; }
.band { position:absolute; top:-4px; height:22px; background:rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.5); border-radius:4px; }
.pin { position:absolute; top:-8px; width:3px; height:30px; background:#fff; border-radius:2px; }
.big { font-size:2rem; font-weight:700; }
.badge { display:inline-block; padding:.15rem .55rem; border-radius:999px; font-size:.75rem; font-weight:600; margin-right:.4rem; }
.b-pass { background:rgba(63,185,127,.15); color:var(--good); }
.b-fail { background:rgba(224,92,79,.15); color:var(--bad); }
.b-warn { background:rgba(224,164,55,.15); color:var(--warn); }
.b-info { background:rgba(90,167,232,.15); color:var(--acc); }
table { width:100%; border-collapse:collapse; font-size:.86rem; }
td, th { padding:.4rem .6rem; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
th { color:var(--dim); font-weight:600; }
.mono { font-family:ui-monospace,Menlo,monospace; font-size:.8rem; color:var(--dim); }
.evidence li { margin:.3rem 0 .3rem 1rem; font-size:.88rem; }
.flag { color:var(--warn); }
.validity { color:var(--dim); font-size:.85rem; font-style:italic; }
.next { border-left:3px solid var(--acc); padding-left:1rem; }
"""

_VERDICT_TMPL = """
<!doctype html><html><head><meta charset="utf-8">
<title>CreativeGate verdict {{ v.id }}</title><style>{{ css }}</style></head><body>
<div class="wrap">
  <h1>CreativeGate verdict &mdash; {{ v.artifact_id }}</h1>
  <div class="sub mono">verdict {{ v.id }} &middot; profile {{ v.profile_name }} &middot; config {{ v.config_hash }}
    &middot; seed {{ v.seed }} &middot; {{ v.created_at.strftime('%Y-%m-%d %H:%M UTC') }}</div>

  <div class="card">
  {% if v.eliminated %}
    <span class="badge b-fail">ELIMINATED</span> at <strong>{{ v.eliminated_by }}</strong>
    <p style="margin-top:.6rem">{{ v.validity_summary }}</p>
  {% elif v.score is not none %}
    <span class="badge {{ 'b-pass' if v.score >= 0.5 else 'b-warn' }}">SURVIVED FUNNEL</span>
    <div class="big">{{ '%.2f'|format(v.score) }}
      {% if v.band %}<span style="font-size:1rem;color:var(--dim)"> &nbsp;[{{ '%.2f'|format(v.band[0]) }} &ndash; {{ '%.2f'|format(v.band[1]) }}]</span>{% endif %}
    </div>
    {% if v.band %}
    <div class="scorebar">
      <div class="band" style="left:{{ (v.band[0]*100)|round(1) }}%; width:{{ ((v.band[1]-v.band[0])*100)|round(1) }}%"></div>
      <div class="pin" style="left:{{ (v.score*100)|round(1) }}%"></div>
    </div>
    <div class="sub">confidence band (wider = less validated evidence behind the number)</div>
    {% endif %}
    <p>{{ v.confidence_note }}</p>
  {% else %}
    <span class="badge b-info">GATE-EVIDENCE ONLY</span>
    <p style="margin-top:.6rem">{{ v.confidence_note }}</p>
  {% endif %}
  </div>

  {% if v.flags %}
  <div class="card"><h2 style="margin-top:0">Flags</h2>
    <ul class="evidence">{% for f in v.flags %}<li class="flag">&#9888; {{ f }}</li>{% endfor %}</ul>
  </div>{% endif %}

  <h2>Rung ledger</h2>
  <div class="card"><table>
    <tr><th>Rung</th><th>Score</th><th>Result</th><th>Fidelity</th><th>Validity (the system's own limits)</th></tr>
    {% for r in v.rung_results %}
    <tr>
      <td>{{ r.rung }} <span class="mono">v{{ r.rung_version }}</span></td>
      <td>{{ '%.3f'|format(r.score) if r.score is not none else '&mdash;'|safe }}</td>
      <td>{% if r.passed %}<span class="badge b-pass">pass</span>{% else %}<span class="badge b-fail">fail</span>{% endif %}</td>
      <td>{% if r.provider_fidelity == 'degraded' %}<span class="badge b-warn">degraded</span>{% else %}<span class="badge b-pass">full</span>{% endif %}</td>
      <td class="validity">{{ r.validity.statement }}</td>
    </tr>
    {% endfor %}
  </table></div>

  <h2>Evidence ledger</h2>
  <div class="card"><ul class="evidence">
    {% for e in v.evidence %}<li><strong>{{ e.source }}</strong> &middot; {{ e.summary }}</li>{% endfor %}
  </ul></div>

  {% if v.next_test %}
  <h2>Cheapest next test</h2>
  <div class="card next">
    <strong>{{ v.next_test.kind.replace('_',' ') }}</strong>
    {% if v.next_test.estimated_cost_usd %} &middot; est. ${{ '%.0f'|format(v.next_test.estimated_cost_usd) }} (planning estimate){% endif %}
    <p style="margin-top:.4rem">{{ v.next_test.rationale }}</p>
    {% if v.next_test.expected_gain %}<p class="sub" style="margin:.4rem 0 0">{{ v.next_test.expected_gain }}</p>{% endif %}
  </div>{% endif %}

  <div class="sub mono">versions: {{ v.versions }} &middot; schema {{ v.schema_version }}</div>
</div></body></html>
"""

_BATCH_TMPL = """
<!doctype html><html><head><meta charset="utf-8">
<title>CreativeGate funnel run</title><style>{{ css }}</style></head><body>
<div class="wrap">
  <h1>CreativeGate funnel run &mdash; {{ title }}</h1>
  <div class="sub">{{ verdicts|length }} artifacts &middot; {{ survivors|length }} survived &middot;
    {{ verdicts|length - survivors|length }} eliminated</div>
  {% if note %}<div class="card">{{ note }}</div>{% endif %}
  <h2>Ranking (survivors, by fused score)</h2>
  <div class="card"><table>
    <tr><th>#</th><th>Artifact</th><th>Score</th><th>Band</th><th>Next test</th><th>Flags</th></tr>
    {% for v in survivors %}
    <tr>
      <td>{{ loop.index }}</td><td>{{ v.artifact_id }}</td>
      <td>{{ '%.3f'|format(v.score) if v.score is not none else '&mdash;'|safe }}</td>
      <td class="mono">{% if v.band %}[{{ '%.2f'|format(v.band[0]) }}&ndash;{{ '%.2f'|format(v.band[1]) }}]{% endif %}</td>
      <td>{{ v.next_test.kind.replace('_',' ') if v.next_test else '' }}</td>
      <td class="flag">{{ v.flags|length or '' }}</td>
    </tr>
    {% endfor %}
  </table></div>
  <h2>Eliminated</h2>
  <div class="card"><table>
    <tr><th>Artifact</th><th>Eliminated by</th><th>Why</th></tr>
    {% for v in verdicts if v.eliminated %}
    <tr><td>{{ v.artifact_id }}</td><td>{{ v.eliminated_by }}</td><td class="validity">{{ v.validity_summary }}</td></tr>
    {% endfor %}
  </table></div>
</div></body></html>
"""

_env = Environment(loader=BaseLoader(), autoescape=False)


def render_verdict_report(verdict: Verdict) -> str:
    return _env.from_string(_VERDICT_TMPL).render(v=verdict, css=_CSS)


def render_batch_report(verdicts: list[Verdict], title: str = "batch", note: str = "") -> str:
    survivors = sorted(
        [v for v in verdicts if not v.eliminated and v.score is not None],
        key=lambda v: v.score, reverse=True,
    )
    return _env.from_string(_BATCH_TMPL).render(
        verdicts=verdicts, survivors=survivors, title=title, note=note, css=_CSS
    )
