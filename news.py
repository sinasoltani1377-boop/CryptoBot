import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

NEWS_SOURCES = {
    "Cointelegraph": "https://cointelegraph.com/rss",
    "CoinDesk": (
        "https://www.coindesk.com/arc/outboundfeeds/rss/"
        "?outputType=xml"
    ),
    "The Block": "https://www.theblock.co/rss.xml",
}

REQUEST_TIMEOUT = 10
MAX_ITEMS_PER_SOURCE = 20
CACHE_SECONDS = 300

_cache = {
    "time": 0,
    "articles": [],
}

_news_lock = asyncio.Lock()


# ============================================================
# KEYWORDS
# ============================================================

CRITICAL_KEYWORDS = [
    "exchange hacked",
    "crypto exchange hack",
    "exchange exploit",
    "bitcoin crash",
    "crypto market crash",
    "exchange insolvency",
    "bankruptcy",
    "major security breach",
    "stablecoin depeg",
    "stablecoin collapse",
    "black swan",
    "market liquidation",
    "flash crash",
    "bitcoin etf rejected",
    "bitcoin etf approval denied",
]

HIGH_KEYWORDS = [
    "bitcoin etf",
    "ethereum etf",
    "sec approves",
    "sec rejects",
    "federal reserve",
    "interest rate",
    "rate decision",
    "rate cut",
    "rate hike",
    "inflation",
    "consumer price index",
    "cpi report",
    "nonfarm payrolls",
    "jobs report",
    "hack",
    "hacked",
    "exploit",
    "lawsuit",
    "sec sues",
    "regulation",
    "sanctions",
    "liquidation",
    "outflows",
    "inflows",
    "bankruptcy",
    "insolvency",
]

BTC_KEYWORDS = [
    "bitcoin",
    "btc",
]

ETH_KEYWORDS = [
    "ethereum",
    "ether",
    "eth ",
]

MARKET_KEYWORDS = [
    "crypto",
    "cryptocurrency",
    "bitcoin",
    "ethereum",
    "blockchain",
    "digital asset",
    "digital assets",
    "stablecoin",
    "defi",
    "exchange",
    "federal reserve",
    "inflation",
    "interest rate",
    "etf",
]


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element, names):
    for child in element.iter():
        if local_name(child.tag) in names:
            if child.text:
                value = clean_text(child.text)

                if value:
                    return value

    return ""


def parse_date(value):
    if not value:
        return None

    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def extract_link(element):
    for child in element.iter():
        if local_name(child.tag) == "link":
            href = child.attrib.get("href")

            if href:
                return href.strip()

            if child.text:
                return child.text.strip()

    return ""


def classify_news(title, summary):
    text = f"{title} {summary}".lower()

    critical = any(
        keyword in text
        for keyword in CRITICAL_KEYWORDS
    )

    high = any(
        keyword in text
        for keyword in HIGH_KEYWORDS
    )

    if critical:
        importance = "CRITICAL"

    elif high:
        importance = "HIGH"

    else:
        importance = "NORMAL"

    if any(keyword in text for keyword in BTC_KEYWORDS):
        asset = "BTC"

    elif any(keyword in text for keyword in ETH_KEYWORDS):
        asset = "ETH"

    elif any(keyword in text for keyword in MARKET_KEYWORDS):
        asset = "MARKET"

    else:
        asset = "UNKNOWN"

    return importance, asset


def parse_feed(xml_data, source):
    articles = []

    root = ET.fromstring(xml_data)

    for item in root.iter():
        tag = local_name(item.tag)

        if tag not in ("item", "entry"):
            continue

        title = child_text(item, {"title"})

        if not title:
            continue

        summary = child_text(
            item,
            {"description", "summary", "encoded"}
        )

        link = extract_link(item)

        published_text = child_text(
            item,
            {"pubdate", "published", "updated", "date"}
        )

        published = parse_date(published_text)

        importance, asset = classify_news(
            title,
            summary
        )

        articles.append({
            "source": source,
            "title": title,
            "summary": summary[:500],
            "link": link,
            "published": (
                published.isoformat()
                if published else None
            ),
            "importance": importance,
            "asset": asset,
        })

        if len(articles) >= MAX_ITEMS_PER_SOURCE:
            break

    return articles


# ============================================================
# FETCH
# ============================================================

def fetch_source(source, url):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "CryptoBot-NewsReader/1.0 "
                "(RSS feed reader)"
            ),
            "Accept": (
                "application/rss+xml, "
                "application/atom+xml, "
                "application/xml, text/xml"
            ),
        },
    )

    with urlopen(
        request,
        timeout=REQUEST_TIMEOUT
    ) as response:

        xml_data = response.read(2_000_000)

    return parse_feed(xml_data, source)


def fetch_all_news():
    all_articles = []
    source_status = {}

    for source, url in NEWS_SOURCES.items():
        try:
            articles = fetch_source(source, url)

            all_articles.extend(articles)

            source_status[source] = {
                "ok": True,
                "count": len(articles),
            }

        except Exception as exc:
            logger.warning(
                "NEWS_SOURCE_ERROR | %s | %s",
                source,
                str(exc)[:200],
            )

            source_status[source] = {
                "ok": False,
                "count": 0,
            }

    # Remove duplicate headlines.
    unique = {}

    for article in all_articles:
        key = article["title"].strip().lower()

        if key not in unique:
            unique[key] = article

    articles = list(unique.values())

    # Sort newest first when publication dates are available.
    articles.sort(
        key=lambda article: article["published"] or "",
        reverse=True,
    )

    return articles, source_status


# ============================================================
# ASYNC PUBLIC API
# ============================================================

async def get_news(force_refresh=False):
    now = time.time()

    if (
        not force_refresh
        and now - _cache["time"] < CACHE_SECONDS
    ):
        return list(_cache["articles"])

    async with _news_lock:
        now = time.time()

        if (
            not force_refresh
            and now - _cache["time"] < CACHE_SECONDS
        ):
            return list(_cache["articles"])

        articles, _ = await asyncio.to_thread(
            fetch_all_news
        )

        # Update cache only if at least one source worked.
        if articles:
            _cache["articles"] = articles
            _cache["time"] = time.time()

        return list(_cache["articles"])


async def get_news_status():
    articles = await get_news()

    critical = [
        article for article in articles
        if article["importance"] == "CRITICAL"
    ]

    high = [
        article for article in articles
        if article["importance"] == "HIGH"
    ]

    return {
        "total": len(articles),
        "critical_count": len(critical),
        "high_count": len(high),
        "critical": critical[:10],
        "high": high[:10],
        "updated_at": (
            datetime.now(timezone.utc).isoformat()
        ),
    }


async def get_latest_news(limit=10):
    articles = await get_news()

    return articles[:max(1, min(limit, 30))]


async def search_news(query, limit=10):
    query = query.strip().lower()

    if not query:
        return []

    articles = await get_news()
    results = []

    for article in articles:
        searchable = (
            article["title"] + " " +
            article["summary"]
        ).lower()

        if query in searchable:
            results.append(article)

        if len(results) >= max(1, min(limit, 30)):
            break

    return results


async def refresh_news():
    return await get_news(force_refresh=True)


# ============================================================
# DIAGNOSTICS
# ============================================================

async def news_diagnostics():
    articles, source_status = await asyncio.to_thread(
        fetch_all_news
    )

    _cache["articles"] = articles
    _cache["time"] = time.time()

    return {
        "sources": source_status,
        "total": len(articles),
        "critical_count": sum(
            1 for article in articles
            if article["importance"] == "CRITICAL"
        ),
        "high_count": sum(
            1 for article in articles
            if article["importance"] == "HIGH"
        ),
}
