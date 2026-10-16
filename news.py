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
    "sources": {},
}

_news_lock = asyncio.Lock()


# ============================================================
# CRITICAL EVENTS
# ============================================================

CRITICAL_KEYWORDS = (
    "exchange hacked",
    "crypto exchange hack",
    "exchange exploit",
    "major exchange hack",
    "major security breach",
    "security breach",
    "private keys stolen",
    "customer funds stolen",
    "exchange withdrawals suspended",
    "withdrawals halted",
    "withdrawals suspended",
    "stablecoin depeg",
    "stablecoin collapse",
    "exchange insolvency",
    "files for bankruptcy",
    "filed for bankruptcy",
    "exchange bankruptcy",
    "liquidation cascade",
    "flash crash",
    "crypto market crash",
    "market-wide selloff",
    "market crash",
    "crypto crash",
    "bitcoin crash",
    "bitcoin crashes",
    "bitcoin plunges",
    "spot bitcoin etf rejected",
    "bitcoin etf rejected",
    "bitcoin etf approval denied",
    "sec rejects spot bitcoin etf",
)


# ============================================================
# HIGH-IMPORTANCE NEWS
# ============================================================

HIGH_KEYWORDS = (
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
    "sanctions",
    "federal reserve",
    "fomc",
    "interest rate",
    "rate decision",
    "rate cut",
    "rate hike",
    "fed cuts rates",
    "fed raises rates",
    "monetary policy",
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
)


# ============================================================
# ASSET KEYWORDS
# ============================================================

BTC_KEYWORDS = (
    "bitcoin",
    "btc",
)

ETH_KEYWORDS = (
    "ethereum",
    "ether",
    "eth",
)

# Explicitly market-wide events and macroeconomic subjects.
# A generic mention of "crypto" alone is not enough to label
# a story as market-wide.
MARKET_WIDE_KEYWORDS = (
    "crypto market",
    "cryptocurrency market",
    "global crypto market",
    "market-wide",
    "market crash",
    "crypto crash",
    "market-wide selloff",
    "liquidation cascade",
    "flash crash",
    "federal reserve",
    "federal funds rate",
    "fomc",
    "interest rate decision",
    "rate decision",
    "monetary policy",
    "consumer price index",
    "producer price index",
    "consumer prices",
    "producer prices",
    "inflation",
    "nonfarm payrolls",
    "jobs report",
    "unemployment rate",
)


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = unescape(str(value))

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_text(value):
    return clean_text(value).casefold()


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element, names):
    for child in element.iter():
        if local_name(child.tag) not in names:
            continue

        if child.text:
            value = clean_text(child.text)

            if value:
                return value

    return ""


def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(timezone.utc)

    except (TypeError, ValueError, OverflowError):
        pass

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


def contains_any(text, terms):
    return any(
        term in text
        for term in terms
    )


# ============================================================
# NEWS CLASSIFICATION
# ============================================================

def classify_news(title, summary):
    title_clean = clean_text(title)
    summary_clean = clean_text(summary)

    text = normalize_text(
        f"{title_clean} {summary_clean}"
    )

    critical = contains_any(
        text,
        CRITICAL_KEYWORDS,
    )

    high = contains_any(
        text,
        HIGH_KEYWORDS,
    )

    if critical:
        importance = "CRITICAL"

    elif high:
        importance = "HIGH"

    else:
        importance = "NORMAL"

    # Asset classification:
    # 1. Explicit market-wide or macro news.
    # 2. Bitcoin-specific news.
    # 3. Ethereum-specific news.
    # 4. Otherwise UNKNOWN.
    #
    # Generic crypto-related words are not enough to assign
    # an article to every market.

    if contains_any(
        text,
        MARKET_WIDE_KEYWORDS,
    ):
        asset = "MARKET"

    elif contains_any(
        text,
        BTC_KEYWORDS,
    ):
        asset = "BTC"

    elif contains_any(
        text,
        ETH_KEYWORDS,
    ):
        asset = "ETH"

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
        if local_name(item.tag) not in (
            "item",
            "entry",
        ):
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

        articles.append({
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
        })

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
            "User-Agent": "CryptoBot-NewsReader/3.0",
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
        xml_data = response.read(2_000_000)

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

            all_articles.extend(articles)

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

    # Deduplicate headlines.
    unique = {}

    for article in all_articles:
        key = normalize_text(
            article.get("title", "")
        )

        if not key:
            continue

        if key not in unique:
            unique[key] = article

    articles = list(unique.values())

    # Sort by publication time.
    # Articles without a date are placed at the end.
    articles.sort(
        key=lambda article: (
            article.get("published") is not None,
            article.get("published") or "",
        ),
        reverse=True,
    )

    working_sources = sum(
        1
        for status in source_status.values()
        if status.get("ok")
    )

    logger.info(
        "NEWS_FETCH_COMPLETE | Articles=%s | "
        "WorkingSources=%s/%s",
        len(articles),
        working_sources,
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
        return list(_cache["articles"])

    async with _news_lock:
        now = time.time()

        if (
            not force_refresh
            and now - _cache["time"] < CACHE_SECONDS
        ):
            return list(_cache["articles"])

        articles, source_status = await asyncio.to_thread(
            fetch_all_news
        )

        working_sources = sum(
            1
            for status in source_status.values()
            if status.get("ok")
        )

        # Keep the last known cache if every source fails.
        if working_sources > 0:
            _cache["articles"] = articles
            _cache["sources"] = source_status
            _cache["time"] = time.time()

        return list(_cache["articles"])


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
        "sources": dict(_cache["sources"]),
        "updated_at": (
            datetime.fromtimestamp(
                _cache["time"],
                timezone.utc,
            ).isoformat()
            if _cache["time"]
            else None
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
    query = normalize_text(query)

    if not query:
        return []

    articles = await get_news()

    results = []

    limit = max(
        1,
        min(int(limit), 30),
    )

    for article in articles:
        searchable = normalize_text(
            article.get("title", "")
            + " "
            + article.get("summary", "")
        )

        if query in searchable:
            results.append(article)

        if len(results) >= limit:
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
    async with _news_lock:
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
            _cache["sources"] = source_status
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
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
