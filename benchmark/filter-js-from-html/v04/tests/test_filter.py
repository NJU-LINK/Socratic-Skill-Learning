import re
import subprocess
import sys
from pathlib import Path


FILTER = Path("/app/filter.py")

LANDING_PAGE_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="daybreak" data-build="2026.06.03">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Northwind Studio Launch</title>
  <link rel="preload" as="image" href="/assets/hero-banner.jpg" imagesizes="100vw">
</head>
<body class="landing-page font-sans text-slate-900" data-site="northwind" aria-busy="false">
  <header class="site-header shell shell--wide" data-analytics-id="hero-001" data-track-label="spring-launch" style="background: linear-gradient(180deg, #f8fbff 0%, #eef4ff 100%); border-bottom: 1px solid #dbe7ff;">
    <nav class="nav nav--desktop" aria-label="Main" data-layout="stack@sm row@lg">
      <a class="nav__brand text-lg tracking-tight" href="/" aria-label="Northwind Studio home">Northwind Studio</a>
      <ul class="nav__links list-reset" data-role="primary-links">
        <li><a class="nav__link" href="/work" data-nav-slot="1">Work</a></li>
        <li><a class="nav__link" href="/pricing" data-nav-slot="2">Pricing</a></li>
        <li><a class="nav__link" href="/contact" data-nav-slot="3">Contact</a></li>
      </ul>
    </nav>
  </header>

  <main class="shell shell--wide grid gap-24" data-template="launch-story">
    <section class="hero grid grid--2col align-center" aria-labelledby="hero-title" data-surface="glass" data-density="comfortable">
      <div class="hero__content" data-column="copy">
        <p class="eyebrow" data-tone="brand">2026 rollout</p>
        <h1 id="hero-title" class="display display--xl tracking-tight">Campaign pages that keep every pixel tidy.</h1>
        <p class="lede text-balance" data-copy-slot="intro">The design team needs aggressive HTML cleanup without stripping the classes, labels, spacing, and metadata our publishing system relies on.</p>
        <form class="cta-row stack@sm row@md" action="/trial" method="post" data-form="hero-cta" aria-label="Hero call to action">
          <input type="email" name="email" placeholder="name@example.com" autocomplete="email" class="input input--lg" data-track-field="email" aria-label="Work email">
          <button class="btn btn--primary btn--lg" type="submit" formaction="javascript:window.alert('hero-cta')" formmethod="post" data-variant="solid" aria-label="Start trial now">Start trial</button>
        </form>
      </div>

      <aside class="hero__panel card shadow-xl" data-column="visual" aria-label="Preview cards">
        <article class="feature-card rounded-3xl border border-sky-100 p-6" data-card="insights" data-owner="design-systems" aria-label="Insights card" style="background-image: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(239,246,255,0.96) 100%), url('javascript:alert(1)'); background-position: center; background-size: cover; border-radius: 24px; min-height: 280px;">
          <img src="/assets/chart-preview.png" alt="Insights dashboard preview" width="480" height="320" loading="lazy" decoding="async" class="w-full rounded-2xl" data-asset-id="chart-preview">
          <h2 class="text-xl mt-4">Live reporting</h2>
          <p class="text-sm text-slate-600">Keep your analytics widgets, semantic labels, and responsive spacing untouched while unsafe snippets disappear.</p>
        </article>
      </aside>
    </section>

    <section class="testimonials grid gap-8" aria-labelledby="testimonial-title" data-section="quotes">
      <h2 id="testimonial-title" class="section-title">What the team cares about</h2>
      <div class="quote-grid grid grid--3col" data-grid="testimonials">
        <blockquote class="quote-card" cite="/stories/mira" data-persona="designer">
          <p>\"We need the cleanup to be surgical. Removing one unsafe fragment should not erase the rest of the component.\"</p>
          <footer>Mira, Design Lead</footer>
        </blockquote>
      </div>
    </section>
  </main>
</body>
</html>
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" data-app="ops-console" data-release="2026.2">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Operations Snapshot</title>
</head>
<body class="dashboard bg-slate-50 text-slate-900" data-page="ops-home" aria-live="polite">
  <div class="shell shell--wide" data-density="compact">
    <header class="page-header flex items-center justify-between" data-region="header" style="padding: 24px 32px; background: #ffffff; border-bottom: 1px solid #e2e8f0;">
      <div>
        <p class="eyebrow" data-status="healthy">Control center</p>
        <h1 class="title" aria-label="Operations Snapshot">Operations Snapshot</h1>
      </div>
      <img src="/assets/avatar-ops.png" alt="Operations team avatar stack" width="96" height="32" loading="lazy" decoding="async" data-image-role="avatars">
    </header>

    <main class="grid grid--dashboard gap-6" data-layout="two-column">
      <section class="panel panel--metrics rounded-2xl" data-panel="throughput" aria-labelledby="throughput-title" style="width: expression(alert('legacy-layout')); min-height: 260px; background: #ffffff; box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08); border-radius: 20px;">
        <div class="panel__head flex items-center justify-between">
          <h2 id="throughput-title" class="panel__title">Throughput</h2>
          <span class="badge badge--success" data-value="stable">Stable</span>
        </div>
        <table class="data-table w-full" aria-describedby="throughput-caption" data-view="summary-table">
          <caption id="throughput-caption">Daily processing summary</caption>
          <thead>
            <tr><th scope="col">Region</th><th scope="col">Jobs</th><th scope="col">Latency</th></tr>
          </thead>
          <tbody>
            <tr><td>East</td><td>418</td><td>82 ms</td></tr>
            <tr><td>West</td><td>403</td><td>89 ms</td></tr>
          </tbody>
        </table>
      </section>

      <aside class="panel panel--preview rounded-2xl" data-panel="preview" aria-label="Embedded preview">
        <iframe class="preview-frame w-full rounded-xl border-0" title="Release preview" src="/previews/release.html" srcdoc="<!DOCTYPE html><html><body><script>top.alert('srcdoc')</script><p>release preview</p></body></html>" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" sandbox="allow-scripts allow-same-origin" data-preview-id="release-card" style="min-height: 280px; background: #ffffff;"></iframe>
      </aside>

      <section class="panel panel--notes rounded-2xl" data-panel="notes" aria-labelledby="notes-title">
        <h2 id="notes-title">Operator notes</h2>
        <p class="text-sm text-slate-600" data-copy-slot="notes">Preserve our labels, dimensions, and data attributes. Only the executable parts should change.</p>
        <a class="text-link" href="/docs/release-checklist" data-doc-kind="runbook" aria-label="Open release checklist">Open release checklist</a>
      </section>
    </main>
  </div>
</body>
</html>
"""


def run_filter(target: Path) -> str:
    subprocess.run([sys.executable, str(FILTER), str(target)], check=True)
    return target.read_text(encoding="utf-8")


def test_safe_markup_is_left_untouched(tmp_path: Path) -> None:
    html = (
        '<a class="nav__link" href="/docs" data-nav-slot="2" '
        'style="color: #123; background-image: linear-gradient(90deg, #fff, #eee);">'
        "Docs</a>"
    )
    target = tmp_path / "safe.html"
    target.write_text(html, encoding="utf-8")

    assert run_filter(target) == html


def test_landing_page_sanitizes_only_unsafe_fragments(tmp_path: Path) -> None:
    target = tmp_path / "landing-page.html"
    target.write_text(LANDING_PAGE_HTML, encoding="utf-8")

    output = run_filter(target)

    assert "javascript:" not in output.lower()
    assert "Northwind Studio" in output
    assert (
        '  <header class="site-header shell shell--wide" data-analytics-id="hero-001" '
        'data-track-label="spring-launch" style="background: linear-gradient(180deg, '
        '#f8fbff 0%, #eef4ff 100%); border-bottom: 1px solid #dbe7ff;">'
    ) in output
    assert re.search(
        r'<button class="btn btn--primary btn--lg" type="submit" formaction="[^"]*" '
        r'formmethod="post" data-variant="solid" aria-label="Start trial now">'
        r'Start trial</button>',
        output,
    )
    assert 'formaction=""' in output
    assert (
        'style="background-image: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, '
        'rgba(239,246,255,0.96) 100%); background-position: center; background-size: cover; '
        'border-radius: 24px; min-height: 280px;"'
    ) in output
    assert 'data-owner="design-systems"' in output
    assert 'data-asset-id="chart-preview"' in output


def test_dashboard_sanitizes_expression_and_srcdoc_without_dropping_panel(tmp_path: Path) -> None:
    target = tmp_path / "dashboard.html"
    target.write_text(DASHBOARD_HTML, encoding="utf-8")

    output = run_filter(target)

    lower = output.lower()
    assert "expression(" not in lower
    assert "<script>top.alert('srcdoc')</script>" not in output
    assert (
        '      <section class="panel panel--metrics rounded-2xl" data-panel="throughput" '
        'aria-labelledby="throughput-title" style=" min-height: 260px; background: #ffffff; '
        'box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08); border-radius: 20px;">'
    ) in output
    assert 'srcdoc=""' in output
    assert 'class="preview-frame w-full rounded-xl border-0"' in output
    assert 'src="/previews/release.html"' in output
    assert 'sandbox="allow-scripts allow-same-origin"' in output
    assert 'data-preview-id="release-card"' in output


def test_custom_mixed_attributes_keep_safe_content(tmp_path: Path) -> None:
    html = (
        '<iframe class="frame" data-id="card-9" title="Preview" src="/ok.html" '
        'srcdoc="<script>alert(1)</script><p>preview</p>" '
        'style="background: #fff; width: expression(alert(1)); '
        'background-image: linear-gradient(#fff, #eee), url(\'javascript:alert(2)\'); '
        'min-height: 20px;" loading="lazy"></iframe>'
    )
    target = tmp_path / "mixed.html"
    target.write_text(html, encoding="utf-8")

    output = run_filter(target)

    assert '<script>alert(1)</script>' not in output
    assert 'srcdoc=""' in output
    assert 'width: expression' not in output
    assert 'background: #fff;' in output
    assert 'background-image: linear-gradient(#fff, #eee);' in output
    assert 'min-height: 20px;' in output
    assert 'class="frame"' in output
    assert 'data-id="card-9"' in output
    assert 'loading="lazy"' in output


def test_inline_event_handlers_are_neutralized_without_losing_safe_attributes(tmp_path: Path) -> None:
    html = (
        '<button class="cta" onclick="alert(1)" onfocus="console.log(2)" '
        'data-id="x" aria-label="Go now" style="color: #123;">Go</button>'
    )
    target = tmp_path / "events.html"
    target.write_text(html, encoding="utf-8")

    output = run_filter(target)

    assert 'onclick=""' in output
    assert 'onfocus=""' in output
    assert 'alert(1)' not in output
    assert 'console.log(2)' not in output
    assert 'class="cta"' in output
    assert 'data-id="x"' in output
    assert 'aria-label="Go now"' in output
    assert 'style="color: #123;"' in output
