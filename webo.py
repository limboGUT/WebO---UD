#!/usr/bin/env python3
"""
WebO v0.0.1
===========
Advanced console-based web content scraper and page analyzer.

WebO fetches a web page (or crawls a whole site), then prints a
super-detailed report covering metadata, SEO, links, images, media,
forms, tables, structured data, security headers, SSL info, detected
technologies, keyword density, contact info, and more -- directly to
your terminal. Reports can also be exported to JSON, CSV, or plain text.

Usage:
    python webo.py example.com
    python webo.py https://example.com --depth 2 --max-pages 50
    python webo.py example.com --check-links --format all
    python webo.py --help

Responsible use: WebO respects robots.txt by default when crawling and
applies a delay between requests. Only scrape sites you have permission
to access, and follow their terms of service and applicable law.

Requirements: requests, beautifulsoup4 (lxml recommended, optional)
License: MIT
"""

import argparse
import csv
import json
import os
import re
import socket
import ssl
import sys
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"

VERSION = "0.0.1"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 WebO/" + VERSION
)
SECTION_WIDTH = 74


# ============================================================
#  COLORS / CONSOLE OUTPUT
# ============================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"


class Reporter:
    """Handles all console output. Also buffers plain-text lines so the
    exact same report can be exported to a .txt file on request."""

    def __init__(self, use_color=True, quiet=False):
        self.use_color = use_color
        self.quiet = quiet
        self.lines = []

    def _wrap(self, text, color):
        if color and self.use_color:
            return f"{color}{text}{C.RESET}"
        return text

    def line(self, text="", color=None):
        self.lines.append(text)
        if not self.quiet:
            print(self._wrap(text, color))

    def section(self, title):
        self.line("")
        title_disp = f" {title} "
        total_pad = max(4, SECTION_WIDTH - len(title_disp))
        left = total_pad // 2
        right = total_pad - left
        self.line("=" * left + title_disp + "=" * right, color=C.BRIGHT_CYAN)

    def subsection(self, title):
        self.line("")
        bar = "-" * max(2, 44 - len(title))
        self.line(f">> {title} {bar}", color=C.CYAN)

    def kv(self, key, value, color=None, indent=1):
        prefix = "    " * indent
        self.line(f"{prefix}{str(key):<24}: {value}", color=color)

    def list_items(self, items, max_items=10, indent=2, color=None):
        prefix = "    " * indent
        items = list(items)
        shown = items[:max_items]
        for it in shown:
            self.line(f"{prefix}- {it}", color=color)
        remaining = len(items) - len(shown)
        if remaining > 0:
            self.line(f"{prefix}... and {remaining} more", color=C.DIM)

    def check(self, passed, label, detail=""):
        icon = "[OK]" if passed else "[X] "
        color = C.BRIGHT_GREEN if passed else C.BRIGHT_RED
        text = f"    {icon} {label}"
        if detail:
            text += f" -- {detail}"
        self.line(text, color=color)

    def banner_box(self, box_lines):
        width = max(len(l) for l in box_lines) + 4
        self.line("+" + "-" * width + "+", color=C.BRIGHT_CYAN)
        for l in box_lines:
            self.line("|" + l.center(width) + "|", color=C.BRIGHT_CYAN)
        self.line("+" + "-" * width + "+", color=C.BRIGHT_CYAN)


def print_banner(reporter):
    reporter.banner_box([
        f"WebO v{VERSION}",
        "Advanced Web Content Scraper & Analyzer",
    ])
    reporter.line("")


# ============================================================
#  CONSTANTS: stopwords / tech signatures / social domains
# ============================================================

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "arent", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "cannot", "could", "couldnt", "did", "didnt", "do", "does", "doesnt",
    "doing", "dont", "down", "during", "each", "few", "for", "from", "further", "had", "hadnt",
    "has", "hasnt", "have", "havent", "having", "he", "hed", "hell", "hes", "her", "here", "heres",
    "hers", "herself", "him", "himself", "his", "how", "hows", "i", "id", "ill", "im", "ive", "if",
    "in", "into", "is", "isnt", "it", "its", "itself", "just", "lets", "me", "more", "most", "my",
    "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "she", "shed", "shell", "shes",
    "should", "shouldnt", "so", "some", "such", "than", "that", "thats", "the", "their", "theirs",
    "them", "themselves", "then", "there", "theres", "these", "they", "theyd", "theyll", "theyre",
    "theyve", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasnt", "we", "wed", "well", "were", "werent", "weve", "what", "whats", "when", "whens",
    "where", "wheres", "which", "while", "who", "whos", "whom", "why", "whys", "with", "wont",
    "would", "wouldnt", "you", "youd", "youll", "youre", "youve", "your", "yours", "yourself",
    "yourselves", "www", "com", "http", "https", "html",
}

TECH_SIGNATURES = {
    "WordPress": [r"wp-content", r"wp-includes", r"/wp-json/"],
    "Shopify": [r"cdn\.shopify\.com", r"Shopify\.theme"],
    "Wix": [r"static\.wixstatic\.com", r"\bwix\.com\b"],
    "Squarespace": [r"squarespace\.com", r"static1\.squarespace\.com"],
    "Drupal": [r"Drupal\.settings", r"/sites/default/files"],
    "Joomla": [r"/media/jui/", r"Joomla!"],
    "React": [r"react(-dom)?(\.min)?\.js", r"data-reactroot", r"__REACT"],
    "Vue.js": [r"vue(\.min)?\.js", r"__vue__", r"data-v-"],
    "Angular": [r"ng-app", r"angular(\.min)?\.js", r"ng-version"],
    "jQuery": [r"jquery[.\-]?(\d[\w.]*)?(\.min)?\.js"],
    "Bootstrap": [r"bootstrap(\.min)?\.css", r"bootstrap(\.min)?\.js"],
    "Google Analytics": [r"google-analytics\.com", r"gtag\(", r"\bga\(\s*['\"]"],
    "Google Tag Manager": [r"googletagmanager\.com"],
    "Cloudflare": [r"cloudflare"],
    "Font Awesome": [r"font-?awesome"],
    "Next.js": [r"__NEXT_DATA__", r"_next/static"],
    "PHP": [r"\.php(\?|\"|'|$)"],
}

SOCIAL_DOMAINS = {
    "facebook.com": "Facebook", "fb.com": "Facebook",
    "twitter.com": "Twitter/X", "x.com": "Twitter/X",
    "instagram.com": "Instagram", "linkedin.com": "LinkedIn",
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "tiktok.com": "TikTok", "pinterest.com": "Pinterest",
    "github.com": "GitHub", "reddit.com": "Reddit",
    "t.me": "Telegram", "wa.me": "WhatsApp",
    "discord.gg": "Discord", "discord.com": "Discord",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_RE = re.compile(r"\+?\d{1,3}?[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")


# ============================================================
#  UTILITIES
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_url(url):
    url = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", url):
        url = "https://" + url
    return url


def default_basename(url):
    netloc = urlparse(url).netloc.replace(":", "_") or "site"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"webo_{netloc}_{ts}"


def human_bytes(n):
    if n is None:
        return "Unknown"
    n = float(n)
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ============================================================
#  EXTRACTION FUNCTIONS (pure functions -> dicts)
# ============================================================

def extract_meta(soup, url):
    meta = {}
    meta["title"] = soup.title.get_text(strip=True) if soup.title else None
    meta["title_length"] = len(meta["title"]) if meta["title"] else 0

    def get_meta(name=None, prop=None):
        if name:
            tag = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        else:
            tag = soup.find("meta", attrs={"property": prop})
        content = tag.get("content") if tag else None
        return content.strip() if content else None

    meta["description"] = get_meta(name="description")
    meta["description_length"] = len(meta["description"]) if meta["description"] else 0
    meta["keywords"] = get_meta(name="keywords")
    meta["author"] = get_meta(name="author")
    meta["viewport"] = get_meta(name="viewport")
    meta["robots"] = get_meta(name="robots")
    meta["generator"] = get_meta(name="generator")

    html_tag = soup.find("html")
    meta["language"] = html_tag.get("lang") if html_tag else None

    canonical = soup.find("link", rel="canonical")
    meta["canonical"] = canonical.get("href") if canonical and canonical.get("href") else None

    favicon = soup.find("link", rel=re.compile("icon", re.I))
    meta["favicon"] = urljoin(url, favicon.get("href")) if favicon and favicon.get("href") else None

    charset_tag = soup.find("meta", attrs={"charset": True})
    meta["charset"] = charset_tag.get("charset") if charset_tag else None

    og = {}
    for tag in soup.find_all("meta", attrs={"property": re.compile("^og:")}):
        key = (tag.get("property") or "").replace("og:", "")
        if key and tag.get("content"):
            og[key] = tag.get("content")
    meta["open_graph"] = og

    twitter = {}
    for tag in soup.find_all("meta", attrs={"name": re.compile("^twitter:")}):
        key = (tag.get("name") or "").replace("twitter:", "")
        if key and tag.get("content"):
            twitter[key] = tag.get("content")
    meta["twitter_card"] = twitter

    return meta


def extract_headings(soup):
    headings = {}
    for level in range(1, 7):
        tag_name = f"h{level}"
        tags = soup.find_all(tag_name)
        headings[tag_name] = [t.get_text(strip=True) for t in tags if t.get_text(strip=True)]
    return headings


def extract_text_stats(html):
    text_soup = BeautifulSoup(html, PARSER)
    for tag in text_soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = text_soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    words = re.findall(r"[A-Za-z']+", text)
    stats = {
        "word_count": len(words),
        "character_count": len(text),
        "estimated_reading_time_min": max(1, round(len(words) / 200)) if words else 0,
        "text_sample": (text[:300] + "...") if len(text) > 300 else text,
    }
    return stats, words, text


def extract_links(soup, base_url):
    base_domain = urlparse(base_url).netloc
    all_links = []
    internal = []
    external = []
    nofollow = 0
    mailto = []
    tel = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        if href.lower().startswith("mailto:"):
            mailto.append(href[7:])
            continue
        if href.lower().startswith("tel:"):
            tel.append(href[4:])
            continue

        full = urljoin(base_url, href).split("#")[0]
        if full in seen:
            continue
        seen.add(full)

        rel = a.get("rel") or []
        if isinstance(rel, str):
            rel = rel.split()
        is_nofollow = "nofollow" in [r.lower() for r in rel]
        if is_nofollow:
            nofollow += 1

        entry = {"url": full, "text": a.get_text(strip=True)[:80], "nofollow": is_nofollow}
        all_links.append(entry)
        if urlparse(full).netloc == base_domain:
            internal.append(entry)
        else:
            external.append(entry)

    external_domains = sorted(set(urlparse(l["url"]).netloc for l in external))
    return {
        "total": len(all_links),
        "internal": internal,
        "external": external,
        "internal_count": len(internal),
        "external_count": len(external),
        "unique_external_domains": external_domains,
        "nofollow_count": nofollow,
        "mailto_count": len(mailto),
        "tel_count": len(tel),
        "mailto": mailto,
        "tel": tel,
    }


def extract_images(soup, base_url):
    images = []
    missing_alt = 0
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src.startswith("data:"):
            src_display = f"[inline data-uri, {len(src)} chars]"
        else:
            src_display = urljoin(base_url, src) if src else None
        alt = img.get("alt")
        if not alt:
            missing_alt += 1
        images.append({"src": src_display, "alt": alt, "width": img.get("width"), "height": img.get("height")})
    return {"count": len(images), "missing_alt_count": missing_alt, "items": images}


def extract_media(soup, base_url):
    videos = [urljoin(base_url, v.get("src")) for v in soup.find_all("video") if v.get("src")]
    for v in soup.find_all("video"):
        for s in v.find_all("source"):
            if s.get("src"):
                videos.append(urljoin(base_url, s.get("src")))
    audios = [urljoin(base_url, a.get("src")) for a in soup.find_all("audio") if a.get("src")]
    embeds = []
    for iframe in soup.find_all("iframe", src=True):
        src = iframe.get("src")
        if any(d in src for d in ["youtube.com", "youtu.be", "vimeo.com", "player.vimeo"]):
            embeds.append(urljoin(base_url, src))
    return {"videos": sorted(set(videos)), "audios": sorted(set(audios)), "embedded_players": embeds}


def extract_scripts_styles(soup, base_url):
    scripts_ext = [urljoin(base_url, s.get("src")) for s in soup.find_all("script", src=True)]
    scripts_inline = len([s for s in soup.find_all("script") if not s.get("src")])
    styles_ext = [urljoin(base_url, l.get("href")) for l in soup.find_all("link", rel="stylesheet") if l.get("href")]
    styles_inline = len(soup.find_all("style"))
    return {
        "external_scripts": scripts_ext,
        "inline_script_count": scripts_inline,
        "external_stylesheets": styles_ext,
        "inline_style_count": styles_inline,
    }


def extract_forms(soup, base_url):
    forms = []
    for f in soup.find_all("form"):
        inputs = []
        has_password = False
        for inp in f.find_all(["input", "textarea", "select"]):
            itype = inp.get("type", "text") if inp.name == "input" else inp.name
            if itype == "password":
                has_password = True
            inputs.append({"name": inp.get("name"), "type": itype})
        action = f.get("action")
        forms.append({
            "action": urljoin(base_url, action) if action else base_url,
            "method": (f.get("method") or "GET").upper(),
            "input_count": len(inputs),
            "inputs": inputs,
            "has_password_field": has_password,
        })
    return forms


def extract_tables(soup):
    tables = []
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        first_row_cols = len(rows[0].find_all(["td", "th"])) if rows else 0
        tables.append({"rows": len(rows), "columns_approx": first_row_cols})
    return tables


def extract_structured_data(soup):
    jsonld_count = 0
    types_found = set()
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            content = json.loads(tag.string or "")
        except Exception:
            continue
        jsonld_count += 1
        items = content if isinstance(content, list) else [content]
        for item in items:
            if isinstance(item, dict) and "@type" in item:
                t = item["@type"]
                if isinstance(t, list):
                    types_found.update(str(x) for x in t)
                else:
                    types_found.add(str(t))
    microdata_types = set()
    for tag in soup.find_all(attrs={"itemtype": True}):
        microdata_types.add(tag.get("itemtype"))
    return {
        "json_ld_count": jsonld_count,
        "json_ld_types": sorted(types_found),
        "microdata_types": sorted(microdata_types),
        "has_structured_data": bool(jsonld_count or microdata_types),
    }


def extract_social_links(all_links):
    found = {}
    for link in all_links:
        netloc = urlparse(link["url"]).netloc.replace("www.", "")
        for domain, name in SOCIAL_DOMAINS.items():
            if domain in netloc and name not in found:
                found[name] = link["url"]
    return found


def extract_contacts(text, mailto_list):
    emails = set(EMAIL_RE.findall(text))
    for m in mailto_list:
        addr = m.split("?")[0].strip()
        if addr:
            emails.add(addr)
    emails = sorted(e for e in emails if not re.search(r"\.(png|jpg|jpeg|gif|svg|webp|css|js)$", e, re.I))

    phones_raw = PHONE_RE.findall(text)
    phones = sorted(set(p.strip() for p in phones_raw if len(re.sub(r"\D", "", p)) >= 7))
    return {"emails": emails, "phones": phones}


def extract_keyword_density(words, top_n=15):
    filtered = [w.lower() for w in words if len(w) > 2 and w.lower().replace("'", "") not in STOPWORDS]
    total = len(filtered)
    counter = Counter(filtered)
    top = counter.most_common(top_n)
    return [{"word": w, "count": c, "density_pct": round(c / total * 100, 2) if total else 0} for w, c in top]


def extract_seo_analysis(meta, headings, images, text_stats, url):
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    title = meta.get("title")
    add("Title tag present", bool(title), title or "Missing <title> tag")
    if title:
        tl = meta["title_length"]
        add("Title length optimal (30-60 chars)", 30 <= tl <= 60, f"{tl} characters")

    desc = meta.get("description")
    desc_preview = (desc[:60] + "...") if desc and len(desc) > 60 else desc
    add("Meta description present", bool(desc), desc_preview or "Missing meta description")
    if desc:
        dl = meta["description_length"]
        add("Description length optimal (120-160 chars)", 120 <= dl <= 160, f"{dl} characters")

    h1_count = len(headings.get("h1", []))
    add("Exactly one H1 tag", h1_count == 1, f"{h1_count} H1 tag(s) found")

    add("Canonical URL set", bool(meta.get("canonical")), meta.get("canonical") or "No canonical link")
    add("Viewport meta (mobile-friendly)", bool(meta.get("viewport")), meta.get("viewport") or "Missing viewport tag")
    add("Language attribute set", bool(meta.get("language")), meta.get("language") or "Missing lang attribute")

    robots_meta = (meta.get("robots") or "").lower()
    add("Not blocking search indexing", "noindex" not in robots_meta, meta.get("robots") or "No robots meta tag")

    img_count = images.get("count", 0)
    missing_alt = images.get("missing_alt_count", 0)
    if img_count:
        add("Images have alt text", missing_alt == 0, f"{missing_alt}/{img_count} images missing alt text")

    add("Uses HTTPS", url.lower().startswith("https"), url.split("://")[0].upper())
    add("Sufficient content length (300+ words)", text_stats.get("word_count", 0) >= 300,
        f"{text_stats.get('word_count', 0)} words")

    passed_count = sum(1 for c in checks if c["passed"])
    total = len(checks) or 1
    return {"checks": checks, "passed": passed_count, "total": len(checks), "score_pct": round(passed_count / total * 100, 1)}


SECURITY_HEADER_NAMES = [
    "Strict-Transport-Security", "Content-Security-Policy", "X-Frame-Options",
    "X-Content-Type-Options", "X-XSS-Protection", "Referrer-Policy", "Permissions-Policy",
]


def extract_security_headers(headers):
    result = {}
    for h in SECURITY_HEADER_NAMES:
        result[h] = headers.get(h)
    present = sum(1 for v in result.values() if v)
    return {"headers": result, "present_count": present, "total": len(SECURITY_HEADER_NAMES)}


def extract_ssl_info(hostname, timeout=5):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
        issuer = dict(x[0] for x in cert.get("issuer", []))
        subject = dict(x[0] for x in cert.get("subject", []))
        not_after = cert.get("notAfter")
        expiry_iso, days_left = None, None
        if not_after:
            expiry_dt = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
            days_left = (expiry_dt - utc_now_naive()).days
            expiry_iso = expiry_dt.isoformat()
        return {
            "valid": True,
            "issuer": issuer.get("organizationName") or issuer.get("commonName"),
            "subject": subject.get("commonName"),
            "expires": expiry_iso,
            "days_until_expiry": days_left,
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def detect_technologies(html, headers):
    found = []
    header_str = " ".join(f"{k}:{v}" for k, v in headers.items())
    combined = html + " " + header_str
    for name, patterns in TECH_SIGNATURES.items():
        for p in patterns:
            if re.search(p, combined, re.I):
                found.append(name)
                break
    return sorted(set(found))


# ============================================================
#  EXPORT FUNCTIONS
# ============================================================

def export_json(report, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)


def export_csv(report, path):
    fieldnames = [
        "url", "status_code", "title", "word_count", "h1_count",
        "internal_links", "external_links", "images", "missing_alt",
        "seo_score_pct", "load_time_sec", "technologies",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in report["pages"]:
            if "meta" not in p:
                writer.writerow({"url": p.get("url"), "status_code": p.get("status_code", "ERROR")})
                continue
            writer.writerow({
                "url": p.get("final_url", p.get("url")),
                "status_code": p.get("status_code"),
                "title": (p.get("meta", {}).get("title") or "")[:120],
                "word_count": p.get("text_stats", {}).get("word_count"),
                "h1_count": len(p.get("headings", {}).get("h1", [])),
                "internal_links": p.get("links", {}).get("internal_count"),
                "external_links": p.get("links", {}).get("external_count"),
                "images": p.get("images", {}).get("count"),
                "missing_alt": p.get("images", {}).get("missing_alt_count"),
                "seo_score_pct": p.get("seo", {}).get("score_pct"),
                "load_time_sec": p.get("elapsed_sec"),
                "technologies": "; ".join(p.get("technologies", [])),
            })


def export_txt(reporter, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(reporter.lines))


# ============================================================
#  REPORT PRINTING
# ============================================================

def print_robots_sitemap(reporter, robots_info, sitemap_info):
    reporter.section("ROBOTS.TXT & SITEMAP")
    reporter.kv("robots.txt", "Found" if robots_info["exists"] else "Not found",
                color=C.GREEN if robots_info["exists"] else C.YELLOW)
    if robots_info["exists"]:
        reporter.kv("Disallow rules", robots_info["disallow_count"])
        if robots_info["sitemaps"]:
            reporter.kv("Sitemaps declared", len(robots_info["sitemaps"]))
    reporter.kv("Sitemap", sitemap_info["found"] or "Not found",
                color=C.GREEN if sitemap_info["found"] else C.YELLOW)


def print_page_report(reporter, page, max_list, index=None, total=None):
    if "meta" not in page:
        label = page.get("url", "unknown")
        reporter.line(f"    [X] FAILED: {label} -- {page.get('error', page.get('skipped', 'unknown error'))}",
                       color=C.BRIGHT_RED)
        return

    label = f"PAGE {index}/{total}: " if index else "PAGE REPORT: "
    reporter.section(f"{label}{page['final_url']}")

    status_color = C.BRIGHT_GREEN if page["status_code"] < 400 else C.BRIGHT_RED
    reporter.kv("Status", f"{page['status_code']} {page['reason']}", color=status_color)
    reporter.kv("Load Time", f"{page['elapsed_sec']}s")
    reporter.kv("Content-Type", page.get("content_type"))
    reporter.kv("Content Size", human_bytes(page["content_length_bytes"]))
    reporter.kv("Server", page["http_headers"].get("Server", "Unknown"))
    if page.get("redirected"):
        reporter.kv("Redirected From", page["url"], color=C.YELLOW)

    m = page["meta"]
    reporter.subsection("Meta & SEO Tags")
    reporter.kv("Title", f"{m['title']}  ({m['title_length']} chars)" if m.get("title") else "MISSING",
                color=None if m.get("title") else C.YELLOW)
    reporter.kv("Description",
                f"{(m['description'] or '')[:100]}  ({m['description_length']} chars)" if m.get("description") else "MISSING",
                color=None if m.get("description") else C.YELLOW)
    reporter.kv("Canonical", m.get("canonical") or "None")
    reporter.kv("Language", m.get("language") or "Not set")
    reporter.kv("Generator", m.get("generator") or "Unknown")
    if m.get("open_graph"):
        reporter.kv("Open Graph Tags", len(m["open_graph"]))
    if m.get("twitter_card"):
        reporter.kv("Twitter Card Tags", len(m["twitter_card"]))

    reporter.subsection("Heading Structure")
    any_heading = False
    for level in range(1, 7):
        tag = f"h{level}"
        items = page["headings"].get(tag, [])
        if items:
            any_heading = True
            reporter.kv(tag.upper(), len(items))
            reporter.list_items(items, max_items=max_list, color=C.DIM)
    if not any_heading:
        reporter.line("    No headings found.", color=C.YELLOW)

    ts = page["text_stats"]
    reporter.subsection("Content Statistics")
    reporter.kv("Word Count", ts["word_count"])
    reporter.kv("Paragraphs", ts.get("paragraph_count", 0))
    reporter.kv("Reading Time", f"~{ts['estimated_reading_time_min']} min")

    l = page["links"]
    reporter.subsection("Links")
    reporter.kv("Total Links", l["total"])
    reporter.kv("Internal", l["internal_count"])
    reporter.kv("External", l["external_count"])
    reporter.kv("Nofollow", l["nofollow_count"])
    reporter.kv("Email links", l["mailto_count"])
    reporter.kv("Phone links", l["tel_count"])
    if l["unique_external_domains"]:
        reporter.kv("External Domains", len(l["unique_external_domains"]))
        reporter.list_items(l["unique_external_domains"], max_items=max_list)

    im = page["images"]
    reporter.subsection("Images")
    reporter.kv("Total Images", im["count"])
    reporter.kv("Missing Alt Text", im["missing_alt_count"],
                color=C.YELLOW if im["missing_alt_count"] else C.GREEN)

    med = page["media"]
    if med["videos"] or med["audios"] or med["embedded_players"]:
        reporter.subsection("Media")
        if med["videos"]:
            reporter.kv("Video files", len(med["videos"]))
        if med["audios"]:
            reporter.kv("Audio files", len(med["audios"]))
        if med["embedded_players"]:
            reporter.kv("Embedded players", len(med["embedded_players"]))
            reporter.list_items(med["embedded_players"], max_items=max_list)

    ss = page["scripts_styles"]
    reporter.subsection("Scripts & Stylesheets")
    reporter.kv("External Scripts", len(ss["external_scripts"]))
    reporter.kv("Inline Scripts", ss["inline_script_count"])
    reporter.kv("External Stylesheets", len(ss["external_stylesheets"]))
    reporter.kv("Inline Styles", ss["inline_style_count"])

    if page["forms"]:
        reporter.subsection("Forms")
        reporter.kv("Form Count", len(page["forms"]))
        for i, f in enumerate(page["forms"], 1):
            flag = "  [LOGIN FORM]" if f["has_password_field"] else ""
            reporter.line(f"    Form {i}: {f['method']} -> {f['action']}  ({f['input_count']} fields){flag}",
                           color=C.DIM)

    if page["tables"]:
        reporter.subsection("Tables")
        reporter.kv("Table Count", len(page["tables"]))

    sd = page["structured_data"]
    if sd["has_structured_data"]:
        reporter.subsection("Structured Data")
        reporter.kv("JSON-LD Blocks", sd["json_ld_count"])
        if sd["json_ld_types"]:
            reporter.list_items(sd["json_ld_types"], max_items=max_list)
        if sd["microdata_types"]:
            reporter.kv("Microdata Types", len(sd["microdata_types"]))

    if page["social_links"]:
        reporter.subsection("Social Media Links")
        for name, url_ in page["social_links"].items():
            reporter.line(f"    {name}: {url_}", color=C.DIM)

    c = page["contacts"]
    if c["emails"] or c["phones"]:
        reporter.subsection("Contact Information Found")
        if c["emails"]:
            reporter.kv("Emails", len(c["emails"]))
            reporter.list_items(c["emails"], max_items=max_list)
        if c["phones"]:
            reporter.kv("Phone numbers", len(c["phones"]))
            reporter.list_items(c["phones"], max_items=max_list)

    if page["keyword_density"]:
        reporter.subsection("Top Keywords")
        for kw in page["keyword_density"][:max_list]:
            reporter.line(f"    {kw['word']:<20} {kw['count']:>4}x   ({kw['density_pct']}%)", color=C.DIM)

    if page["technologies"]:
        reporter.subsection("Detected Technologies")
        reporter.line("    " + ", ".join(page["technologies"]), color=C.MAGENTA)

    reporter.subsection("Security")
    sec = page["security_headers"]
    reporter.kv("Security Headers Present", f"{sec['present_count']}/{sec['total']}",
                color=C.GREEN if sec["present_count"] >= 4 else C.YELLOW)
    if page.get("ssl_info"):
        si = page["ssl_info"]
        if si.get("valid"):
            reporter.kv("SSL Certificate",
                        f"Valid -- expires {str(si.get('expires'))[:10]} ({si.get('days_until_expiry')} days left)",
                        color=C.GREEN)
        else:
            reporter.kv("SSL Certificate", f"Could not verify -- {si.get('error')}", color=C.YELLOW)
    else:
        reporter.kv("SSL Certificate", "N/A (not HTTPS)")

    seo = page["seo"]
    reporter.subsection("SEO Checklist")
    for chk in seo["checks"]:
        reporter.check(chk["passed"], chk["name"], chk["detail"])
    reporter.line(f"    Score: {seo['passed']}/{seo['total']}  ({seo['score_pct']}%)", color=C.BOLD)


def print_crawl_summary(reporter, pages):
    reporter.section(f"CRAWL SUMMARY -- {len(pages)} pages visited")
    ok_pages = [p for p in pages if "meta" in p]
    failed = [p for p in pages if "meta" not in p]

    reporter.kv("Pages scraped successfully", len(ok_pages))
    if failed:
        reporter.kv("Pages failed / skipped", len(failed), color=C.YELLOW)

    if ok_pages:
        total_words = sum(p["text_stats"]["word_count"] for p in ok_pages)
        total_images = sum(p["images"]["count"] for p in ok_pages)
        total_internal = sum(p["links"]["internal_count"] for p in ok_pages)
        total_external = sum(p["links"]["external_count"] for p in ok_pages)
        avg_seo = round(sum(p["seo"]["score_pct"] for p in ok_pages) / len(ok_pages), 1)
        avg_load = round(sum(p["elapsed_sec"] for p in ok_pages) / len(ok_pages), 3)

        reporter.kv("Total words (all pages)", total_words)
        reporter.kv("Total images (all pages)", total_images)
        reporter.kv("Total internal links", total_internal)
        reporter.kv("Total external links", total_external)
        reporter.kv("Average SEO score", f"{avg_seo}%")
        reporter.kv("Average load time", f"{avg_load}s")

        reporter.subsection("Pages Overview")
        for i, p in enumerate(ok_pages, 1):
            title = (p["meta"].get("title") or "(no title)")[:55]
            reporter.line(f"  {i:>2}. [{p['status_code']}] {title}", color=C.DIM)
            reporter.line(f"      {p['final_url']}", color=C.DIM)
            reporter.line(
                f"      words={p['text_stats']['word_count']}  links={p['links']['total']}  "
                f"images={p['images']['count']}  seo={p['seo']['score_pct']}%",
                color=C.DIM,
            )

    if failed:
        reporter.subsection("Failed / Skipped Pages")
        for p in failed:
            reason = p.get("error") or p.get("skipped") or "unknown"
            reporter.line(f"  [X] {p.get('url')} -- {reason}", color=C.YELLOW)


def print_link_validation(reporter, lv):
    reporter.section("LINK VALIDATION")
    reporter.kv("Links Checked", lv["checked"])
    reporter.kv("Working", lv["ok_count"], color=C.GREEN)
    reporter.kv("Broken", lv["broken_count"], color=C.RED if lv["broken_count"] else C.GREEN)
    if lv["broken"]:
        reporter.subsection("Broken Links Detail")
        for b in lv["broken"][:50]:
            code = b.get("status_code") or "ERR"
            extra = f" ({b['error']})" if b.get("error") else ""
            reporter.line(f"  [X] [{code}] {b['url']}{extra}", color=C.RED)
        if len(lv["broken"]) > 50:
            reporter.line(f"  ... and {len(lv['broken']) - 50} more", color=C.DIM)


# ============================================================
#  CORE SCRAPER
# ============================================================

class WebOScraper:
    def __init__(self, args):
        self.start_url = args.url
        self.depth = args.depth
        self.max_pages = args.max_pages
        self.delay = args.delay
        self.timeout = args.timeout
        self.retries = max(1, args.retries)
        self.retry_backoff = args.retry_backoff
        self.check_links = args.check_links
        self.link_check_workers = args.link_workers
        self.full_detail = args.full_detail
        self.ignore_robots = args.ignore_robots
        self.skip_ssl = args.skip_ssl_check
        self.insecure = args.insecure
        self.user_agent = args.user_agent

        self.custom_headers = {}
        for h in args.header:
            if ":" in h:
                k, v = h.split(":", 1)
                self.custom_headers[k.strip()] = v.strip()

        self.formats = args.format or []
        self.output_basename = args.output
        self.output_dir = args.output_dir
        self.max_list = 10 ** 9 if args.full else args.max_list
        self.show_banner = not args.no_banner
        self.quiet = args.quiet

        self.session = requests.Session()
        self.reporter = Reporter(use_color=not args.no_color, quiet=args.quiet)

        if self.insecure:
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass

    # -------------------- networking --------------------

    def _headers(self):
        headers = {"User-Agent": self.user_agent}
        headers.update(self.custom_headers)
        return headers

    def fetch(self, url, method="GET"):
        last_err = None
        for attempt in range(1, self.retries + 1):
            try:
                start = time.time()
                resp = self.session.request(
                    method, url, headers=self._headers(), timeout=self.timeout,
                    allow_redirects=True, verify=not self.insecure,
                )
                elapsed = time.time() - start
                return resp, elapsed, None
            except requests.exceptions.RequestException as e:
                last_err = e
                if attempt < self.retries:
                    time.sleep(self.retry_backoff * attempt)
        return None, None, last_err

    # -------------------- robots / sitemap --------------------

    def check_robots(self, base_url):
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        resp, elapsed, err = self.fetch(robots_url)
        if err or resp is None or resp.status_code != 200:
            return {"exists": False, "url": robots_url, "content": None,
                     "disallow_count": 0, "disallow_rules": [], "sitemaps": []}
        text = resp.text
        disallow_rules = re.findall(r"(?im)^\s*Disallow:\s*(\S*)", text)
        sitemaps = re.findall(r"(?im)^\s*Sitemap:\s*(\S+)", text)
        return {
            "exists": True, "url": robots_url, "content": text,
            "disallow_count": len(disallow_rules), "disallow_rules": disallow_rules,
            "sitemaps": sitemaps,
        }

    def build_robot_parser(self, base_url, robots_content):
        rp = RobotFileParser()
        parsed = urlparse(base_url)
        rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        rp.parse((robots_content or "").splitlines())
        return rp

    def find_sitemap(self, base_url, robots_info):
        parsed = urlparse(base_url)
        candidates = list(robots_info.get("sitemaps") or [])
        candidates += [
            f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
            f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        ]
        seen, checked, found = [], [], None
        for c in candidates:
            if c in seen:
                continue
            seen.append(c)
            resp, elapsed, err = self.fetch(c)
            exists = bool(resp is not None and resp.status_code == 200)
            checked.append({"url": c, "exists": exists, "status_code": resp.status_code if resp else None})
            if exists and not found:
                found = c
        return {"found": found, "checked": checked}

    # -------------------- page parsing --------------------

    def _safe(self, page, key, func, *fargs, default):
        try:
            page[key] = func(*fargs)
        except Exception as e:
            page[key] = default
            page.setdefault("_errors", []).append(f"{key}: {e}")

    def parse_page(self, requested_url, resp, elapsed):
        html = resp.text
        soup = BeautifulSoup(html, PARSER)
        final_url = resp.url

        page = {
            "url": requested_url,
            "final_url": final_url,
            "redirected": final_url != requested_url,
            "redirect_chain": [r.url for r in resp.history],
            "fetched_at": utc_now().isoformat(),
            "status_code": resp.status_code,
            "reason": resp.reason,
            "elapsed_sec": round(elapsed, 3),
            "content_type": resp.headers.get("Content-Type"),
            "encoding": resp.encoding,
            "content_length_bytes": len(resp.content),
            "http_headers": dict(resp.headers),
        }

        try:
            stats, words, text = extract_text_stats(html)
            stats["paragraph_count"] = len(soup.find_all("p"))
            page["text_stats"] = stats
        except Exception as e:
            words, text = [], ""
            page["text_stats"] = {"word_count": 0, "character_count": 0,
                                    "estimated_reading_time_min": 0, "paragraph_count": 0, "text_sample": ""}
            page.setdefault("_errors", []).append(f"text_stats: {e}")

        self._safe(page, "meta", extract_meta, soup, final_url, default={})
        self._safe(page, "headings", extract_headings, soup, default={})
        self._safe(page, "links", extract_links, soup, final_url, default={
            "total": 0, "internal": [], "external": [], "internal_count": 0, "external_count": 0,
            "unique_external_domains": [], "nofollow_count": 0, "mailto_count": 0, "tel_count": 0,
            "mailto": [], "tel": [],
        })
        self._safe(page, "images", extract_images, soup, final_url, default={"count": 0, "missing_alt_count": 0, "items": []})
        self._safe(page, "media", extract_media, soup, final_url, default={"videos": [], "audios": [], "embedded_players": []})
        self._safe(page, "scripts_styles", extract_scripts_styles, soup, final_url, default={
            "external_scripts": [], "inline_script_count": 0, "external_stylesheets": [], "inline_style_count": 0,
        })
        self._safe(page, "forms", extract_forms, soup, final_url, default=[])
        self._safe(page, "tables", extract_tables, soup, default=[])
        self._safe(page, "structured_data", extract_structured_data, soup, default={
            "json_ld_count": 0, "json_ld_types": [], "microdata_types": [], "has_structured_data": False,
        })

        all_links_flat = page["links"]["internal"] + page["links"]["external"]
        self._safe(page, "social_links", extract_social_links, all_links_flat, default={})
        self._safe(page, "contacts", extract_contacts, text, page["links"].get("mailto", []), default={"emails": [], "phones": []})
        self._safe(page, "keyword_density", extract_keyword_density, words, default=[])
        self._safe(page, "seo", extract_seo_analysis, page["meta"], page["headings"], page["images"], page["text_stats"], final_url,
                    default={"checks": [], "passed": 0, "total": 0, "score_pct": 0})
        self._safe(page, "security_headers", extract_security_headers, resp.headers, default={"headers": {}, "present_count": 0, "total": 0})

        if final_url.lower().startswith("https") and not self.skip_ssl:
            try:
                hostname = urlparse(final_url).hostname
                page["ssl_info"] = extract_ssl_info(hostname, timeout=self.timeout)
            except Exception as e:
                page["ssl_info"] = {"valid": False, "error": str(e)}
        else:
            page["ssl_info"] = None

        self._safe(page, "technologies", detect_technologies, html, resp.headers, default=[])

        return page

    # -------------------- crawling --------------------

    def crawl(self, start_url, robots_info):
        base_domain = urlparse(start_url).netloc
        rp = self.build_robot_parser(start_url, robots_info.get("content"))

        visited = set()
        queue = deque([(start_url, 0)])
        pages = []

        while queue and len(pages) < self.max_pages:
            url, depth = queue.popleft()
            norm = url.split("#")[0]
            if norm in visited:
                continue
            visited.add(norm)

            if not self.ignore_robots and not rp.can_fetch(self.user_agent, norm):
                self.reporter.line(f"  [robots-blocked] {norm}", color=C.DIM)
                continue

            self.reporter.line(f"  -> [{len(pages) + 1}/{self.max_pages}] depth {depth}: {norm}", color=C.BRIGHT_BLUE)
            resp, elapsed, err = self.fetch(norm)
            if err or resp is None:
                pages.append({"url": norm, "error": str(err) if err else "Unknown error"})
                if self.delay:
                    time.sleep(self.delay)
                continue

            ctype = resp.headers.get("Content-Type", "")
            if "text/html" not in ctype.lower():
                pages.append({"url": norm, "final_url": resp.url, "status_code": resp.status_code,
                               "skipped": f"non-HTML content ({ctype or 'unknown'})"})
                if self.delay:
                    time.sleep(self.delay)
                continue

            page = self.parse_page(norm, resp, elapsed)
            pages.append(page)

            if depth < self.depth:
                for link in page.get("links", {}).get("internal", []):
                    lu = link["url"].split("#")[0]
                    if lu not in visited and urlparse(lu).netloc == base_domain:
                        queue.append((lu, depth + 1))

            if self.delay:
                time.sleep(self.delay)

        return pages

    # -------------------- link validation --------------------

    def validate_links(self, links):
        def check_one(link_url):
            headers = self._headers()
            try:
                r = self.session.head(link_url, headers=headers, timeout=self.timeout,
                                        allow_redirects=True, verify=not self.insecure)
                if r.status_code in (405, 501) or r.status_code >= 400:
                    r = self.session.get(link_url, headers=headers, timeout=self.timeout,
                                           allow_redirects=True, verify=not self.insecure, stream=True)
                return {"url": link_url, "status_code": r.status_code, "ok": r.status_code < 400}
            except requests.exceptions.RequestException as e:
                return {"url": link_url, "status_code": None, "ok": False, "error": str(e)[:150]}

        urls = [l["url"] for l in links]
        results = []
        with ThreadPoolExecutor(max_workers=self.link_check_workers) as ex:
            futures = {ex.submit(check_one, u): u for u in urls}
            for fut in as_completed(futures):
                results.append(fut.result())

        broken = [r for r in results if not r["ok"]]
        return {"checked": len(results), "ok_count": len(results) - len(broken),
                 "broken_count": len(broken), "broken": broken, "all": results}

    # -------------------- export --------------------

    def export_report(self, report):
        base = self.output_basename or default_basename(report["target"])
        formats = self.formats
        if "all" in formats:
            formats = ["json", "csv", "txt"]
        os.makedirs(self.output_dir, exist_ok=True)
        paths = []
        if "json" in formats:
            p = os.path.join(self.output_dir, base + ".json")
            export_json(report, p)
            paths.append(p)
        if "csv" in formats:
            p = os.path.join(self.output_dir, base + ".csv")
            export_csv(report, p)
            paths.append(p)
        if "txt" in formats:
            p = os.path.join(self.output_dir, base + ".txt")
            export_txt(self.reporter, p)
            paths.append(p)
        return paths

    # -------------------- orchestration --------------------

    def run(self):
        if self.show_banner:
            print_banner(self.reporter)

        url = normalize_url(self.start_url)
        mode_desc = (f"Crawl (depth={self.depth}, max={self.max_pages} pages)"
                     if self.depth > 0 else "Single Page")
        self.reporter.line(f"Target      : {url}", color=C.BOLD)
        self.reporter.line(f"Mode        : {mode_desc}")
        self.reporter.line(f"User-Agent  : {self.user_agent}", color=C.DIM)
        self.reporter.line("")

        t0 = time.time()

        self.reporter.line("Checking robots.txt and sitemap...", color=C.DIM)
        robots_info = self.check_robots(url)
        sitemap_info = self.find_sitemap(url, robots_info)

        if self.depth > 0:
            self.reporter.line(f"\nStarting crawl...", color=C.BRIGHT_BLUE)
            pages = self.crawl(url, robots_info)
        else:
            resp, elapsed, err = self.fetch(url)
            if err or resp is None:
                self.reporter.line(f"\n[X] ERROR: Could not fetch {url}", color=C.BRIGHT_RED)
                self.reporter.line(f"    {err}", color=C.RED)
                return None
            pages = [self.parse_page(url, resp, elapsed)]

        ok_pages = [p for p in pages if "meta" in p]

        link_validation = None
        if self.check_links:
            seen = {}
            for p in ok_pages:
                for l in p["links"]["internal"] + p["links"]["external"]:
                    seen[l["url"]] = l
            unique_links = list(seen.values())
            if unique_links:
                self.reporter.line(f"\nValidating {len(unique_links)} unique links (this may take a moment)...",
                                     color=C.BRIGHT_BLUE)
                link_validation = self.validate_links(unique_links)

        total_elapsed = time.time() - t0

        report = {
            "tool": f"WebO v{VERSION}",
            "target": url,
            "generated_at": utc_now().isoformat(),
            "mode": "crawl" if self.depth > 0 else "single",
            "depth": self.depth,
            "pages_scraped": len(pages),
            "pages_ok": len(ok_pages),
            "total_time_sec": round(total_elapsed, 2),
            "robots_txt": robots_info,
            "sitemap": sitemap_info,
            "link_validation": link_validation,
            "pages": pages,
        }

        print_robots_sitemap(self.reporter, robots_info, sitemap_info)

        if self.depth > 0:
            if self.full_detail:
                for i, p in enumerate(ok_pages, 1):
                    print_page_report(self.reporter, p, self.max_list, index=i, total=len(ok_pages))
            print_crawl_summary(self.reporter, pages)
        else:
            for p in pages:
                print_page_report(self.reporter, p, self.max_list)

        if link_validation:
            print_link_validation(self.reporter, link_validation)

        self.reporter.section("DONE")
        self.reporter.kv("Total Time", f"{report['total_time_sec']}s")
        self.reporter.kv("Pages Scraped", f"{report['pages_ok']}/{report['pages_scraped']}")

        export_paths = []
        if self.formats:
            export_paths = self.export_report(report)
            for p in export_paths:
                self.reporter.line(f"  Saved: {p}", color=C.GREEN)
        report["export_paths"] = export_paths

        return report


# ============================================================
#  CLI
# ============================================================

EPILOG = """
Examples:
  python webo.py example.com
  python webo.py https://example.com --depth 2 --max-pages 50
  python webo.py example.com --format all -o my_report
  python webo.py example.com --check-links --full-detail
  python webo.py example.com --no-color --quiet --format json
  python webo.py example.com -H "Authorization: Bearer TOKEN"
"""


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="webo.py",
        description=f"WebO v{VERSION} -- Advanced Web Content Scraper & Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    p.add_argument("url", nargs="?", default=None,
                    help="Target URL to scan (scheme optional, https assumed)")
    p.add_argument("-d", "--depth", type=int, default=0,
                    help="Crawl depth: 0 = single page only (default), 1+ = follow internal links N levels deep")
    p.add_argument("--max-pages", type=int, default=25, help="Maximum pages to crawl (default: 25)")
    p.add_argument("--delay", type=float, default=0.5, help="Delay in seconds between crawl requests (default: 0.5)")
    p.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10)")
    p.add_argument("--retries", type=int, default=3, help="Retry attempts per request (default: 3)")
    p.add_argument("--retry-backoff", type=float, default=1.0,
                    help="Base seconds between retries, multiplied by attempt number (default: 1.0)")
    p.add_argument("--check-links", action="store_true", help="Validate every discovered link's HTTP status")
    p.add_argument("--link-workers", type=int, default=10, help="Concurrent workers for link validation (default: 10)")
    p.add_argument("--full-detail", action="store_true",
                    help="In crawl mode, print the full detailed report for every page (default: summary only)")
    p.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt rules while crawling")
    p.add_argument("--skip-ssl-check", action="store_true", help="Skip SSL certificate inspection")
    p.add_argument("--insecure", action="store_true", help="Disable SSL certificate verification (like curl -k)")
    p.add_argument("-A", "--user-agent", default=DEFAULT_UA, help="Custom User-Agent string")
    p.add_argument("-H", "--header", action="append", default=[], metavar="KEY:VALUE",
                    help='Custom request header, repeatable (e.g. -H "Authorization: Bearer xyz")')
    p.add_argument("--format", nargs="+", choices=["json", "csv", "txt", "all"], default=None,
                    help="Export report to file(s) in given format(s)")
    p.add_argument("-o", "--output", default=None, help="Output filename base (without extension)")
    p.add_argument("--output-dir", default=".", help="Directory to save exported files (default: current directory)")
    p.add_argument("--max-list", type=int, default=10,
                    help="Max items shown per list in console output before truncating (default: 10)")
    p.add_argument("--full", action="store_true", help="Do not truncate lists in console output")
    p.add_argument("--no-color", action="store_true", help="Disable colored output")
    p.add_argument("--no-banner", action="store_true", help="Suppress the startup banner")
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress console output (useful with --format)")
    p.add_argument("-V", "--version", action="version", version=f"WebO v{VERSION}")
    return p


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.url:
        if sys.stdin.isatty():
            try:
                args.url = input("Enter target URL to scan: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nNo URL provided. Exiting.")
                sys.exit(1)
        if not args.url:
            parser.error("the following arguments are required: url")

    scraper = WebOScraper(args)
    try:
        report = scraper.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if report is not None else 1)


if __name__ == "__main__":
    main()
