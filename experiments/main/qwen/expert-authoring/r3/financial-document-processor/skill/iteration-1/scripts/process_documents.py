#!/usr/bin/env python3
"""Financial document processor - production version."""
import os, re, csv, sys, shutil, subprocess
from PIL import Image

DOCS_DIR, INVOICES_DIR, OTHER_DIR = "/app/documents", "/app/invoices", "/app/other"
SUMMARY_PATH = os.path.join(INVOICES_DIR, "summary.csv")
PSM_MODES = ["3", "4", "6"]
OCR_SWAPS = [('5','6'),('6','5'),('8','9'),('9','8')]

def extract_text_pdf(path):
    try:
        r = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True, timeout=30)
        t = r.stdout.strip()
        if len(t) > 20: return [t], False
    except: pass
    try:
        import fitz, pytesseract
        doc = fitz.open(path); texts = []
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            for psm in PSM_MODES:
                try:
                    t = pytesseract.image_to_string(img, config=f"--psm {psm} --oem 3")
                    if t.strip(): texts.append(t.strip())
                except: continue
        doc.close(); return (texts if texts else [""], True)
    except ImportError: return ([""], True)

def extract_text_image(path):
    import pytesseract
    img = Image.open(path); texts = []
    for psm in PSM_MODES:
        try:
            t = pytesseract.image_to_string(img, config=f"--psm {psm} --oem 3")
            if t.strip(): texts.append(t.strip())
        except: continue
    if not texts or max(len(t) for t in texts) < 50:
        gray = img.convert("L")
        for psm in PSM_MODES:
            try:
                t = pytesseract.image_to_string(gray, config=f"--psm {psm} --oem 3")
                if t.strip(): texts.append(t.strip())
            except: continue
    return (texts if texts else [""], True)

def extract_texts(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf": return extract_text_pdf(path)
    elif ext in (".jpg",".jpeg",".png",".gif",".bmp",".webp",".tiff",".tif"):
        return extract_text_image(path)
    return ([""], False)

_DISCLAIMER_PATS = [r'not\s+a\s+tax\s+invoice', r'not\s+an?\s+invoice',
    r'this\s+notice\s+is\s+not', r'this\s+document\s+is\s+not\s+an?\s+invoice']

def classify_document(texts):
    best_text = max(texts, key=len) if texts else ""
    masked = []
    for t in texts:
        for p in _DISCLAIMER_PATS:
            t = re.sub(p, ' [DISCLAIMER] ', t, flags=re.IGNORECASE)
        masked.append(t)
    al = [t.lower() for t in masked]
    score = 0
    for pat, pts in [(r'\binvoice\b',20),(r'\brecei\w*',15),(r'\bbilling\b',15),
        (r'\bbill\b',12),(r'\bcharge\s*na\w*',15),(r'\bcharge\s*sheet',15),
        (r'\btax\s*document\b',15),(r'\btax\s*invoice\b',15),(r'\bremittance\b',15),
        (r'\bstatement\b',12),(r'\bsales\s*note\b',12),(r'\bdelivery\s*note\b',12)]:
        for low in al:
            if re.search(pat, low): score += pts; break
    for pat, pts in [(r'\bpayment\s+reminder\b',-20),(r'\bpurchase\s+order\b',-20),
        (r'\brequisition\b',-20),(r'\bexpense\s+report\b',-15),(r'\bexpense\s+claim\b',-15),
        (r'\breimbursement\b',-15),(r'\bpayroll\b',-15),(r'\btimesheet\b',-15),
        (r'\bquote\b',-12),(r'\bestimate\b',-12),(r'\bproposal\b',-12),(r'\binternal\b',-10)]:
        for low in al:
            if re.search(pat, low): score += pts; break
    for low in al:
        if re.search(r'\breminder\b', low) and not re.search(r'payment\s+reminder', low):
            score -= 8; break
    for low in al:
        if re.search(r'\bpo\s+number\b', low): score -= 10; break
    for low in al:
        if re.search(r'approval\s+status\s*:\s*pending', low): score -= 10; break
    for low in al:
        if re.search(r'\btax\s*:', low): score += 4; break
    for low in al:
        if re.search(r'\bvat\b', low): score += 4; break
    for low in al:
        if re.search(r'(grand\s+total|amount\s+due|payable\s+total|total\s+paid|total\s+due)', low):
            score += 3; break
    for low in al:
        if re.search(r'(\bremit\b|card\s+payment|services?\s*[\d$]|freight\s*[\d$])', low):
            score += 2; break
    return ("invoice" if score >= 5 else "other", best_text)

def _is_date_like(v): return 2015 <= v <= 2035
def parse_amount(s):
    s = s.strip().rstrip(".,").replace(",", "")
    for o,n in [("O","0"),("o","0"),("l","1"),("I","1")]: s = s.replace(o, n)
    try: return float(s)
    except: return None
def infer_decimal(raw):
    s = raw.strip().replace(",", "").rstrip(".,")
    for o,n in [("O","0"),("o","0"),("l","1"),("I","1")]: s = s.replace(o, n)
    if not s.isdigit():
        v = parse_amount(s)
        return [v] if v is not None and v > 0 else []
    cands = set(); cands.add(float(s))
    if len(s)>=2: cands.add(float(s[:-1]+"."+s[-1:]))
    if len(s)>=3: cands.add(float(s[:-2]+"."+s[-2:]))
    return [c for c in cands if c > 0 and not _is_date_like(c)]
def _ocr_corrected_decimals(value):
    s = f"{value:.2f}".replace(".", "")
    corrections = set()
    for i, ch in enumerate(s):
        for old, new in OCR_SWAPS:
            if ch == old:
                corrected = s[:i] + new + s[i+1:]
                try:
                    v = float(corrected) / 100.0
                    if v > 0 and not _is_date_like(v): corrections.add(round(v, 2))
                except: pass
    return list(corrections)
def _line_amounts(line):
    c = []
    for m in re.finditer(r'[\d,]+\.\d{1,2}', line):
        v = parse_amount(m.group())
        if v and v > 0 and not _is_date_like(v): c.append(v)
    if not c:
        for m in re.finditer(r'(?<!\d)(\d{2,5})(?!\d)', line):
            for v in infer_decimal(m.group(1)):
                if v > 0 and not _is_date_like(v): c.append(v)
    return c
def _extract_from_single_text(text):
    totals, vats, subs, svcs, all_amts = [], [], [], [], []
    for line in text.split("\n"):
        low = line.lower()
        line_std = [parse_amount(m.group()) for m in re.finditer(r'[\d,]+\.\d{1,2}', line)]
        line_std = [v for v in line_std if v and v > 0 and not _is_date_like(v)]
        all_amts.extend(line_std)
        for m in re.finditer(r'(?<!\d)(\d{2,5})(?!\d)', line):
            for v in infer_decimal(m.group(1)):
                if v > 0 and not _is_date_like(v): all_amts.append(v)
        if re.search(r'(grand\s*total|total\s*due|amount\s*due|payable\s*total|'
                      r'total\s*payable|total\s*paid|balance\s*due|net\s*payable|'
                      r'total\s*amount|net\s*charges)', low):
            totals.extend(_line_amounts(line))
        elif re.search(r'\btotal\b', low) and not re.search(r'(subtot|sub\s*tot|estimated)', low):
            totals.extend(_line_amounts(line))
        vat_match = False
        if re.search(r'(vat|gst|sales\s*tax|tax\s*included|vat\s*included|'
                      r'tax\s*amount|estimated\s*tax|prior\s*tax)', low):
            vat_match = True
        elif re.search(r'\bast\s*\d', low) or re.search(r'\bast\b', low): vat_match = True
        elif re.search(r'\bta[xk]\b', low): vat_match = True
        elif re.search(r'\btax\b', low): vat_match = True
        if vat_match:
            cands = [c for c in _line_amounts(line) if not _is_date_like(c)]
            vats.extend(cands)
        if re.search(r'(sub\s*tot|subtot|net\s*before)', low):
            subs.extend(_line_amounts(line))
        if re.search(r'(services?\b|freight|consulting|design\s*retainer|'
                      r'hardware|retainer|meals\b)', low):
            svcs.extend(line_std)
    return totals, vats, subs, svcs, all_amts

def _resolve(all_t, all_v, all_s, all_sv, all_a, labeled_vats_set):
    if not all_t or not all_v: return None, -999
    best, best_score = None, -999
    for t in all_t:
        for v in all_v:
            if v >= t or v <= 0 or t <= 0: continue
            sub = round(t - v, 2)
            score = 0
            rate = v / sub if sub > 0 else 0
            if 0.03 <= rate <= 0.30: score += 20
            for s in all_s:
                if abs(sub - s) < 0.05: score += 15
            for sv in all_sv:
                if abs(sub - sv) < 0.05: score += 8
            for a in all_a:
                if abs(sub - a) < 0.05 and abs(a-t)>0.01 and abs(a-v)>0.01:
                    score += 5
            if v in labeled_vats_set and 0.03 <= rate <= 0.30:
                has_match = False
                for a in all_a:
                    if abs(sub - a) < 0.05 and abs(a-t)>0.01 and abs(a-v)>0.01:
                        has_match = True; break
                if not has_match:
                    for s in all_s + all_sv:
                        if abs(sub - s) < 0.05: has_match = True; break
                if has_match: score += 10
            if 0.04 <= rate <= 0.25: score += 3
            elif 0.01 <= rate <= 0.40: score += 1
            score += t / 10000
            if score > best_score:
                best_score = score; best = (round(t, 2), round(v, 2))
    return best, best_score

def extract_amounts(texts, is_ocr=False):
    all_t, all_v, all_s, all_sv, all_a = [], [], [], [], []
    for text in texts:
        t, v, s, sv, a = _extract_from_single_text(text)
        all_t.extend(t); all_v.extend(v)
        all_s.extend(s); all_sv.extend(sv)
        all_a.extend(a)
    all_t = list(set(all_t)); all_v = list(set(all_v))
    all_s = list(set(all_s)); all_sv = list(set(all_sv + all_s))
    all_a = list(set(all_a))
    labeled_vats = set(all_v)
    if all_t and all_sv:
        for t in list(all_t):
            for sv in all_sv:
                if sv < t:
                    iv = round(t - sv, 2)
                    if iv > 0 and not _is_date_like(iv):
                        rate = iv / sv if sv > 0 else 0
                        if 0.03 <= rate <= 0.30: all_v.append(iv)
    all_v = list(set(all_v))
    for s in list(set(all_s + all_sv)):
        for v in labeled_vats:
            syn = round(s + v, 2)
            if syn > 0: all_t.append(syn)
    all_t = list(set(all_t))
    result, score = _resolve(all_t, all_v, all_s, all_sv, all_a, labeled_vats)
    if score >= 30 or not is_ocr:
        if result: return result
    if is_ocr:
        corr_t, corr_v, corr_sv = set(), set(), set()
        for t in all_t:
            for c in _ocr_corrected_decimals(t): corr_t.add(c)
        for v in all_v:
            for c in _ocr_corrected_decimals(v): corr_v.add(c)
        for sv in all_sv:
            for c in _ocr_corrected_decimals(sv): corr_sv.add(c)
        ext_t = list(set(all_t + list(corr_t)))
        ext_v = list(set(all_v + list(corr_v)))
        ext_sv = list(set(all_sv + list(corr_sv)))
        for s in list(set(all_s + ext_sv)):
            for v in labeled_vats:
                syn = round(s + v, 2)
                if syn > 0: ext_t.append(syn)
        ext_t = list(set(ext_t))
        result2, score2 = _resolve(ext_t, ext_v, all_s, ext_sv, all_a, labeled_vats)
        if score2 > score and result2: return result2
    return result if result else (None, None)

def main():
    os.makedirs(INVOICES_DIR, exist_ok=True); os.makedirs(OTHER_DIR, exist_ok=True)
    if not os.path.isdir(DOCS_DIR): sys.exit(1)
    exts = {".pdf",".jpg",".jpeg",".png",".gif",".bmp",".webp",".tiff",".tif"}
    files = sorted(f for f in os.listdir(DOCS_DIR) if os.path.splitext(f)[1].lower() in exts)
    if not files: return
    invoices = []
    for fname in files:
        src = os.path.join(DOCS_DIR, fname)
        texts, is_ocr = extract_texts(src)
        if not texts or all(not t.strip() for t in texts):
            shutil.move(src, os.path.join(OTHER_DIR, fname)); continue
        doc_type, _ = classify_document(texts)
        if doc_type == "invoice":
            total, vat = extract_amounts(texts, is_ocr=is_ocr)
            print(f"{fname}: invoice -> total={total}, vat={vat}")
            invoices.append((fname, total, vat))
            shutil.move(src, os.path.join(INVOICES_DIR, fname))
        else:
            print(f"{fname}: other")
            shutil.move(src, os.path.join(OTHER_DIR, fname))
    total_sum = vat_sum = 0.0
    with open(SUMMARY_PATH, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename","total_amount","vat_amount"])
        for fn, tot, vat in sorted(invoices, key=lambda x: x[0]):
            t = tot if tot is not None else 0.0
            v = vat if vat is not None else 0.0
            total_sum += t; vat_sum += v
            w.writerow([fn, f"{t:.2f}", f"{v:.2f}"])
        w.writerow(["total", f"{total_sum:.2f}", f"{vat_sum:.2f}"])
    print(f"\nInvoices: {len(invoices)}, Total: {total_sum:.2f}, VAT: {vat_sum:.2f}")

if __name__ == "__main__":
    main()
