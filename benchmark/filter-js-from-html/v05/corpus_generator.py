"""Adversarial HTML corpus for the browser-normalization task variant.

The later test suite can import this module to synthesize a wide range of
messy executable samples while keeping the task assets self-contained.
"""

from __future__ import annotations

import base64
import html
import json
import urllib.parse


def _b64_html(payload: str) -> str:
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def _entity_encode(text: str) -> str:
    return "".join(html.escape(ch) if ch in "<>&\"'" else ch for ch in text)


def _percent_encode(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def clean_html_samples() -> list[str]:
    return [
        """<!DOCTYPE html>
<html>
<head><title>Status Board</title></head>
<body>
  <main>
    <h1>Quarterly update</h1>
    <p>Revenue is up 14% and hiring remains open.</p>
    <table>
      <tr><th>Region</th><th>Result</th></tr>
      <tr><td>North</td><td>Strong</td></tr>
    </table>
  </main>
</body>
</html>""",
        """<section class="card card--notice" data-team="ops">
  <h2>Maintenance window</h2>
  <p>Please save your work before 22:00 UTC.</p>
  <a href="/status">View status page</a>
</section>""",
        """<!DOCTYPE html>
<html>
<body>
  <form action="/signup" method="post">
    <label>Email <input type="email" name="email" required></label>
    <button type="submit">Join</button>
  </form>
</body>
</html>""",
    ]


def dangerous_html_samples() -> list[str]:
    script = "<script>alert('alpha')</script>"
    entity_script = _entity_encode("<script>alert('entity')</script>")
    pct_script = _percent_encode("javascript:alert('pct')")
    embedded = "<script>confirm(7)</script>"
    embedded_b64 = _b64_html(embedded)
    nested_svg = "<svg><g onload=alert('svg')></g></svg>"
    nested_svg_entity = _entity_encode(nested_svg)
    doc = "<html><body><script>alert('doc')</script><p>ok</p></body></html>"

    return [
        script,
        "<ScRiPt >alert('case')</ScRiPt>",
        "<img src=x onerror='alert(1)'>",
        "<body onpageshow='alert(2)'><p>hello</p></body>",
        f'<a href="javascript:alert(3)">open</a>',
        f'<a href="{pct_script}">open</a>',
        (
            '<iframe src="data:text/html;base64,'
            + embedded_b64
            + '"></iframe>'
        ),
        (
            '<object data="data:text/html;base64,'
            + embedded_b64
            + '"></object>'
        ),
        '<meta http-equiv="refresh" content="0;url=javascript:alert(4)">',
        '<form action="javascript:alert(5)"><input type="submit"></form>',
        '<button formaction="javascript:alert(6)">Ship</button>',
        nested_svg,
        '<math><maction actiontype="statusline" xlink:href="javascript:alert(8)"></maction></math>',
        '<div style="background-image:url(javascript:alert(9))">x</div>',
        "<<script>alert('broken');//<</script>",
        entity_script,
        nested_svg_entity,
        '<template><img src=x onerror="alert(10)"></template><div>later</div>',
        '<iframe srcdoc="<script>alert(11)</script>"></iframe>',
        '<svg><foreignObject><iframe src="javascript:alert(12)"></iframe></foreignObject></svg>',
        '<input type="image" formaction="javascript:alert(13)" src="/safe.png">',
        '<details open ontoggle="alert(14)"><summary>More</summary></details>',
        doc,
    ]


def wrapped_corpus() -> list[dict[str, str]]:
    wrappers = [
        "<!DOCTYPE html>\n<html><head><title>{name}</title></head><body>{payload}</body></html>",
        "<html><body><div class=outer><p>prefix</p>{payload}<footer>suffix</footer></div></body></html>",
        "<table><tr><td>{payload}</td><td>notes</td></tr></table>",
        "<template id=t>{payload}</template><section>preview</section>",
        "<svg><foreignObject>{payload}</foreignObject></svg>",
    ]

    corpus = []
    for index, payload in enumerate(dangerous_html_samples()):
        wrapper = wrappers[index % len(wrappers)]
        corpus.append(
            {
                "name": f"dangerous-{index:02d}",
                "payload": payload,
                "document": wrapper.format(name=f"Sample {index}", payload=payload),
            }
        )

    for index, payload in enumerate(clean_html_samples()):
        corpus.append(
            {
                "name": f"clean-{index:02d}",
                "payload": payload,
                "document": payload,
            }
        )

    return corpus


def corpus_json() -> str:
    return json.dumps(wrapped_corpus(), indent=2)
