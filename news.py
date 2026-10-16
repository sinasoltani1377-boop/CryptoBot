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
# CRITICAL NEWS KEYWORDS
# ============================================================

CRITICAL_KEYWORDS = [
    # Exchange and security events
    "exchange hacked",
    "crypto exchange hack",
    "exchange exploit",
    "major exchange hack",
    "major security breach",
    "security breach",
    "private keys stolen",
    "customer funds stolen",
    "exchange withdrawals suspended",

    # Market crashes
    "bitcoin crash",
    "bitcoin crashes",
    "bitcoin plunges",
    "crypto market crash",
    "crypto crash",
    "market crash",
    "market-wide selloff",
    "liquidation cascade",
    "flash crash",

    # Stablecoins and insolvency
    "stablecoin depeg",
    "stablecoin collapse",
    "bankruptcy",
    "files for bankruptcy",
    "exchange insolvency",
    "insolvency",
    "withdrawals halted",

    # Major ETF decisions
    "bitcoin etf rejected",
    "bitcoin etf approval denied",
    "sec rejects spot bitcoin etf",
    "spot bitcoin etf rejected",
]


# ============================================================
# HIGH-IMPORTANCE NEWS KEYWORDS
# ============================================================

HIGH_KEYWORDS = [
    # ETFs and regulation
    "bitcoin etf",
    "ethereum etf",
    "spot etf approved",
    "spot etf rejected",
    "sec approves",
    "sec rejects",
    "sec sues",
    "sec lawsuit",
    "crypto regulation",
    "crypto regulations",
    "regulation",
    "sanctions",

    # Central banks and monetary policy
    "federal reserve",
    "fomc",
    "interest rate",
    "rate decision",
    "rate cut",
    "rate hike",
    "fed cuts rates",
    "fed raises rates",
    "monetary policy",

    # Inflation and economic data
    "inflation",
    "consumer price index",
    "producer price index",
    "cpi report",
    "ppi report",
    "consumer prices",
    "producer prices",
    "nonfarm payrolls",
    "jobs report",
    "unemployment rate",
    "economic data",

    # Security and financial risks
    "hack",
    "hacked",
    "exploit",
    "security breach",
    "bankruptcy",
    "insolvency",
    "liquidation",
    "outflows",
    "inflows",
    "withdrawals suspended",
]


# ============================================================
# ASSET KEYWORDS
# ============================================================

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
    "crypto market",
    "cryptocurrency market",
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
    "fomc",
    "inflation",
    "interest rate",
    "producer price",
    "consumer price",
    "cpi",
    "ppi",
    "etf",
]


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = re.sub(
        r"<[^>]+>",
        " ",
        str(value),
    )

    value = unescape(value)

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

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

    value = str(value).strip()

    # Standard RSS date
    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(timezone.utc)

    except (TypeError, ValueError, OverflowError):
        pass

    # ISO-8601 date
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(timezone.utc)

    except (TypeError, ValueError, OverflowError):
        return None


def extract_link(element):
    for child in element.iter():
        if local_name(child.tag) != "link":
            continue

        href = child.attrib.get("href")

        if href:
            return href.strip()

        if child.text:
            link = child.text.strip()

            if link:
                return link

    return ""


# ============================================================
# NEWS CLASSIFICATION
# ============================================================

def classify_news(title, summary):
    title = clean_text(title).lower()
    summary = clean_text(summary).lower()

    text = f"{title} {summary}"

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

    # Macro and market-wide reports should not be
    # assigned exclusively to BTC or ETH.
    market_macro_keywords = [
        "federal reserve",
        "fomc",
        "inflation",
        "consumer price index",
        "producer price index",
        "consumer prices",
        "producer prices",
        "interest rate",
        "rate decision",
        "nonfarm payrolls",
        "jobs report",
        "unemployment rate",
        "crypto market",
        "cryptocurrency market",
        "market crash",
        "crypto crash",
        "liquidation cascade",
        "flash crash",
    ]

    if any(
        keyword in text
        for keyword in market_macro_keywords
    ):
        asset = "MARKET"

    elif any(
        keyword in text
        for keyword in BTC_KEYWORDS
    ):
        asset = "BTC"

    elif any(
        keyword in text
        for keyword in ETH_KEYWORDS
    ):
        asset = "ETH"

    elif any(
        keyword in text
        for keyword in MARKET_KEYWORDS
    ):
        asset = "MARKET"

    else:
        asset = "UNKNOWN"

    return importance, asset


# ============================================================
# RSS / ATOM PARSER
# ============================================================

def parse_feed(xml_data, source):
    articles = []

    try:
        root = ET.fromstring(xml_data)

    except ET.ParseError:
        logger.warning(
            "NEWS_XML_PARSE_ERROR | %s",
            source,
        )
        return articles

    for item in root.iter():
        tag = local_name(item.tag)

        if tag not in ("item", "entry"):
            continue

        title = child_text(
            item,
            {"title"},
        )

        if not title:
            continue

        summary = child_text(
            item,
            {
                "description",
                "summary",
                "encoded",
                "content",
            },
        )

        link = extract_link(item)

        published_text = child_text(
            item,
            {
                "pubdate",
                "published",
                "updated",
                "date",
                "issued",
                "created",
            },
        )

        published = parse_date(
            published_text
        )

        importance, asset = classify_news(
            title,
            summary,
        )

        article = {
            "source": source,
            "title": title,
            "summary": summary[:500],
            "link": link,
            "published": (
                published.isoformat()
                if published
                else None
            ),
            "importance": importance,
            "asset": asset,
        }

        articles.append(article)

        if len(articles) >= MAX_ITEMS_PER_SOURCE:
            break

    return articles


# ============================================================
# FETCH SINGLE SOURCE
# ============================================================

def fetch_source(source, url):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "CryptoBot-NewsReader/2.0"
            ),
            "Accept": (
                "application/rss+xml, "
                "application/atom+xml, "
                "application/xml, "
                "text/xml"
            ),
        },
    )

    with urlopen(
        request,
        timeout=REQUEST_TIMEOUT,
    ) as response:
        xml_data = response.read(
            2_000_000
        )

    return parse_feed(
        xml_data,
        source,
    )


# ============================================================
# FETCH ALL SOURCES
# ============================================================

def fetch_all_news():
    all_articles = []
    source_status = {}

    for source, url in NEWS_SOURCES.items():
        try:
            articles = fetch_source(
                source,
                url,
            )

            all_articles.extend(
                articles
            )

            source_status[source] = {
                "ok": True,
                "count": len(articles),
            }

            logger.info(
                "NEWS_SOURCE_OK | %s | Articles=%s",
                source,
                len(articles),
            )

        except Exception as exc:
            logger.warning(
                "NEWS_SOURCE_ERROR | %s | %s",
                source,
                str(exc)[:200],
            )

            source_status[source] = {
                "ok": False,
                "count": 0,
                "error": str(exc)[:200],
            }

    # Remove duplicate headlines.
    unique = {}

    for article in all_articles:
        key = (
            article.get("title", "")
            .strip()
            .lower()
        )

        if not key:
            continue

        if key not in unique:
            unique[key] = article

    articles = list(
        unique.values()
    )

    # Sort newest first.
    articles.sort(
        key=lambda article: (
            article.get("published") or ""
        ),
        reverse=True,
    )

    logger.info(
        "NEWS_FETCH_COMPLETE | Articles=%s | "
        "WorkingSources=%s/%s",
        len(articles),
        sum(
            1 for status in source_status.values()
            if status.get("ok")
        ),
        len(NEWS_SOURCES),
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
        return list(
            _cache["articles"]
        )

    async with _news_lock:
        now = time.time()

        if (
            not force_refresh
            and now - _cache["time"] < CACHE_SECONDS
        ):
            return list(
                _cache["articles"]
            )

        articles, source_status = await asyncio.to_thread(
            fetch_all_news
        )

        working_sources = sum(
            1
            for status in source_status.values()
            if status.get("ok")
        )

        # Refresh the cache when at least one source
        # responds successfully, even if it has no items.
        if working_sources > 0:
            _cache["articles"] = articles
            _cache["time"] = time.time()

        return list(
            _cache["articles"]
        )


async def get_news_status():
    articles = await get_news()

    critical = [
        article
        for article in articles
        if article.get("importance") == "CRITICAL"
    ]

    high = [
        article
        for article in articles
        if article.get("importance") == "HIGH"
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

    limit = max(
        1,
        min(int(limit), 30),
    )

    return articles[:limit]


async def search_news(query, limit=10):
    query = str(
        query or ""
    ).strip().lower()

    if not query:
        return []

    articles = await get_news()

    results = []

    for article in articles:
        searchable = (
            article.get("title", "")
            + " "
            + article.get("summary", "")
        ).lower()

        if query in searchable:
            results.append(article)

        if len(results) >= max(
            1,
            min(int(limit), 30),
        ):
            break

    return results


async def refresh_news():
    return await get_news(
        force_refresh=True
    )


# ============================================================
# DIAGNOSTICS
# ============================================================

async def news_diagnostics():
    articles, source_status = await asyncio.to_thread(
        fetch_all_news
    )

    working_sources = sum(
        1
        for status in source_status.values()
        if status.get("ok")
    )

    if working_sources > 0:
        _cache["articles"] = articles
        _cache["time"] = time.time()

    critical_count = sum(
        1
        for article in articles
        if article.get("importance") == "CRITICAL"
    )

    high_count = sum(
        1
        for article in articles
        if article.get("importance") == "HIGH"
    )

    return {
        "sources": source_status,
        "total": len(articles),
        "critical_count": critical_count,
        "high_count": high_count,
        "working_sources": working_sources,
        "updated_at": (
            datetime.now(timezone.utc).isoformat()
        ),
    }
