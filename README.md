* **WEBO - Under Development**
WebO fetches a web page (or crawls a whole site), then prints a detailed report covering metadata, SEO, links, images, media, forms, tables, structured data, security headers, SSL info, detected technologies, keyword density, contact info, and more — directly to your terminal. Reports can also be exported to JSON, CSV, or plain text.

WebO is explicitly made for Lightweight and Safe Scraping.

* **Commands (`com`):**
```bash
python webo.py example.com
python webo.py https://example.com --depth 2 --max-pages 50
python webo.py example.com --format all -o my_report
python webo.py example.com --check-links --full-detail
python webo.py example.com --no-color --quiet --format json
python webo.py example.com -H "Authorization: Bearer TOKEN"

```
*Choose within these options!*
Don't know what you are doing? Type in the terminal:
```bash
python webo.py --help
```
to see the commands (`com`). If you feel lost, just type it!

**Responsible use:** WebO respects `robots.txt` by default when crawling and applies a delay between requests. Only scrape sites you have permission to access, and follow their terms of service and applicable law.
**Requirements:** `requests`, `beautifulsoup4` (`lxml` recommended, optional)

**License:** MIT
