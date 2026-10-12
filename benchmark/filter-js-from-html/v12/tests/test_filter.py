from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(os.environ.get('APP_ROOT', '/app'))
FIXTURES = json.loads((ROOT / 'data' / 'fixtures.json').read_text())


def run_filter(html: str, tmp_path: Path) -> str:
    sample = tmp_path / 'sample.html'
    sample.write_text(html, encoding='utf-8')
    subprocess.run([sys.executable, str(ROOT / 'filter.py'), str(sample)], check=True)
    return sample.read_text(encoding='utf-8')


def fixture(name: str) -> str:
    for item in FIXTURES:
        if item['name'] == name:
            return item['html']
    raise KeyError(name)


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, 'html.parser')


def test_dangerous_form_and_link_targets_are_neutralized(tmp_path: Path) -> None:
    checkout = parse_html(run_filter(fixture('checkout-inline-submit'), tmp_path))
    checkout_form = checkout.find('form', id='checkout-form')
    assert checkout_form is not None
    assert checkout_form.get('action') == '#'
    assert checkout_form.get('aria-describedby') == 'checkout-help'
    assert checkout.find('input', id='full-name').get('value') == 'Ada Lovelace'

    express = parse_html(run_filter(fixture('checkout-percent-encoded-formaction'), tmp_path))
    buttons = {button.get('class', [None])[0]: button for button in express.find_all('button')}
    assert buttons['pay-now'].get('formaction') == '#'
    assert buttons['pay-now'].get('aria-label') == 'Pay now'
    assert buttons['save-cart'].get('formaction') == '/cart/save'
    assert express.find('form').get('action') == '/orders'

    contact = parse_html(run_filter(fixture('contact-data-url-link'), tmp_path))
    chat_link = contact.find('a', class_='chat-link')
    email_link = contact.find('a', class_='email-link')
    assert chat_link is not None
    assert chat_link.get('href') == '#'
    assert chat_link.get('target') == 'supportFrame'
    assert chat_link.get('rel') == ['noopener']
    assert email_link is not None
    assert email_link.get('href') == 'mailto:support@example.test'

    account = parse_html(run_filter(fixture('nav-target-iframe'), tmp_path))
    billing_link = account.find('a', class_='danger')
    assert billing_link is not None
    assert billing_link.get('href') == '#'
    assert billing_link.get('target') == 'contentFrame'
    assert account.find('iframe').get('src') == '/account/panel'

    admin = parse_html(run_filter(fixture('admin-meta-refresh'), tmp_path))
    refresh = admin.find('meta', attrs={'http-equiv': lambda value: value and value.lower() == 'refresh'})
    assert refresh is not None
    assert refresh.get('content') == '0; url=#'
    assert admin.find('p').get_text(strip=True) == 'Redirecting to the admin panel...'


def test_safe_documents_remain_unchanged(tmp_path: Path) -> None:
    for name in ['contact-safe-form', 'nav-safe-links', 'safe-meta-refresh']:
        original = fixture(name)
        sanitized = run_filter(original, tmp_path)
        assert sanitized == original


def test_only_unsafe_target_is_changed_on_mixed_document(tmp_path: Path) -> None:
    sanitized = parse_html(run_filter(fixture('contact-data-url-link'), tmp_path))
    chat_link = sanitized.find('a', class_='chat-link')
    email_link = sanitized.find('a', class_='email-link')
    assert chat_link is not None
    assert chat_link.get('href') == '#'
    assert chat_link.get('rel') == ['noopener']
    assert chat_link.get('target') == 'supportFrame'
    assert chat_link.get_text(strip=True) == 'Open chat'
    assert email_link is not None
    assert email_link.get('href') == 'mailto:support@example.test'
    assert email_link.get('rel') == ['nofollow']
    assert email_link.get_text(strip=True) == 'Email us'
    assert sanitized.find('p').get_text(strip=True) == 'Choose the channel that works best for you.'


def test_obfuscated_targets_are_neutralized_without_breaking_safe_content(tmp_path: Path) -> None:
    html = '''<!DOCTYPE html>
<html>
<head>
  <title>Obfuscated Targets</title>
  <meta http-equiv="refresh" content="0; url=JaVa%53CrIpT:alert(5)">
</head>
<body class="admin-shell dense">
  <form id="contact" class="stacked" action="java&#x0D;script:alert(1)" method="post" aria-label="Support request">
    <input type="text" name="subject" value="Billing question">
    <button class="primary" type="submit" formaction="jAvA\tScRiPt:alert(2)">Send</button>
    <button class="secondary" type="submit" formaction="/tickets/save">Save draft</button>
  </form>
  <nav aria-label="Account links">
    <a class="danger-link" href="data:text/html,%253Cscript%253Ealert(3)%253C/script%253E" target="contentFrame">Open portal</a>
    <a class="safe-link" href="/account/overview" target="_self">Overview</a>
  </nav>
</body>
</html>'''

    sanitized_text = run_filter(html, tmp_path)
    sanitized = parse_html(sanitized_text)

    assert 'javascript:' not in sanitized_text.lower()
    assert 'data:text/html' not in sanitized_text.lower()

    refresh = sanitized.find('meta', attrs={'http-equiv': lambda value: value and value.lower() == 'refresh'})
    assert refresh is not None
    assert refresh.get('content') == '0; url=#'

    form = sanitized.find('form', id='contact')
    assert form is not None
    assert form.get('action') == '#'
    assert form.get('method') == 'post'
    assert form.get('aria-label') == 'Support request'
    assert sanitized.find('input', attrs={'name': 'subject'}).get('value') == 'Billing question'

    buttons = {button.get('class', [None])[0]: button for button in sanitized.find_all('button')}
    assert buttons['primary'].get('formaction') == '#'
    assert buttons['primary'].get_text(strip=True) == 'Send'
    assert buttons['secondary'].get('formaction') == '/tickets/save'

    danger_link = sanitized.find('a', class_='danger-link')
    safe_link = sanitized.find('a', class_='safe-link')
    assert danger_link is not None
    assert danger_link.get('href') == '#'
    assert danger_link.get('target') == 'contentFrame'
    assert danger_link.get_text(strip=True) == 'Open portal'
    assert safe_link is not None
    assert safe_link.get('href') == '/account/overview'
    assert safe_link.get('target') == '_self'
    assert safe_link.get_text(strip=True) == 'Overview'
