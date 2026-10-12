import pytest
from PIL import Image, ImageDraw, ImageFont


@pytest.fixture(scope='session')
def explicit_tax_fixture(tmp_path_factory):
    fixture_dir = tmp_path_factory.mktemp('fixtures')
    fixture_path = fixture_dir / 'explicit-tax-no-subtotal.png'

    image = Image.new('RGB', (1800, 1400), color='white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    lines = [
        'INVOICE',
        '',
        'Stonebridge Office Supply',
        'Bill To: Willow Creek Retail',
        'Invoice Number: SB-4401',
        'Invoice Date: 2026-06-15',
        'Payment Terms: Net 20',
        'Remit To: Stonebridge Office Supply Treasury',
        'Line Items',
        'Document storage cartons ............... 500.00',
        'Barcode labels ........................ 300.00',
        'VAT .................................... 80.00',
        'Amount Due ............................ 880.00',
        'Total ................................. 880.00',
    ]

    y = 80
    for line in lines:
        draw.text((100, y), line, fill='black', font=font)
        y += 56

    image.save(fixture_path)
    return fixture_path
