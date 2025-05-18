from flask import Flask, jsonify
import feedparser
from datetime import datetime, timedelta
from datetime import timezone
import html
import os
import re
from flask_caching import Cache
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

app = Flask(__name__)

# Configure Flask-Caching
app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 60  # 1 minute
cache = Cache(app)

# Initialize VADER sentiment analyzer
analyzer = SentimentIntensityAnalyzer()

# Extended crypto sentiment keywords
POSITIVE_WORDS = {
    'gain', 'soar', 'surge', 'rally', 'moon', 'pump', 'bull run', 'green', 'ath',
    'rise', 'adoption', 'all-time high', 'breakout', 'etf approved', 'support',
    'buy', 'buying', 'halving', 'halvening', 'institutional', 'btc halving',
    'expansion', 'partnership', 'launch', 'recover', 'listing', 'funding', 'backed'
}

NEGATIVE_WORDS = {
    'dump', 'plunge', 'dip', 'rekt', 'bearish', 'collapse', 'fud', 'scam', 'crash',
    'liquidated', 'selloff', 'downtrend', 'resistance', 'decline', 'freeze', 'rugpull',
    'lawsuit', 'ban', 'exploit', 'hacked', 'breach', 'layoffs', 'shut down', 'warning'
}

def clean_text(text):
    if not text:
        return ''

    text = strip_html(text)
    text = html.unescape(text)

    replacements = {
        '\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-', '\xa0': ' '
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def strip_html(raw_html):
    if not raw_html:
        return ''
    # Remove <style>, <script>, and <link> blocks entirely
    raw_html = re.sub(r'<(script|style|link).*?>.*?</\1>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw_html = re.sub(r'</?(br|p|div)[^>]*>', '\n', raw_html, flags=re.IGNORECASE)
    return re.sub(r'<.*?>', '', raw_html)

def truncate(text, max_length=400):
    if len(text) <= max_length:
        return text

    # Try breaking after a full stop
    sentences = re.split(r'(?<=\.)\s+', text)
    result = ''
    for sentence in sentences:
        if len(result) + len(sentence) > max_length:
            break
        result += sentence + ' '
    return result.strip()

def get_sentiment_label(text):
    txt = text.lower()

    # Check for both bullish and bearish terms
    positive_matches = any(word in txt for word in POSITIVE_WORDS)
    negative_matches = any(word in txt for word in NEGATIVE_WORDS)

    if positive_matches and negative_matches:
        return 'Mixed'
    if positive_matches:
        return 'Bullish'
    if negative_matches:
        return 'Bearish'

    # Fall back to VADER
    score = analyzer.polarity_scores(text)['compound']
    if score >= 0.1:
        return 'Bullish'
    elif score <= -0.1:
        return 'Bearish'
    return 'Neutral'

# RSS feeds with tags
RSS_FEEDS = {
    # Crypto News
    'CoinDesk': ('https://www.coindesk.com/arc/outboundfeeds/rss/', 'Crypto News'),
    'Cointelegraph': ('https://cointelegraph.com/rss', 'Crypto News'),
    'Decrypt': ('https://decrypt.co/feed/rss', 'Crypto News'),
    'CryptoSlate': ('https://cryptoslate.com/feed/', 'Crypto News'),
    'BeInCrypto': ('https://beincrypto.com/feed/', 'Crypto News'),
    'Bitcoin.com': ('https://news.bitcoin.com/feed/', 'Crypto News'),
    'NewsBTC': ('https://www.newsbtc.com/feed/', 'Crypto News'),
    'AmbCrypto': ('https://ambcrypto.com/feed', 'Crypto News'),
    'CryptoNews.com': ('https://cryptonews.com/news/feed', 'Crypto News'),
    'Blockonomi': ('https://blockonomi.com/feed/', 'Crypto News'),
    'DailyCoin': ('https://dailycoin.com/feed/', 'Crypto News'),
    'CoinGape': ('https://coingape.com/feed', 'Crypto News'),

    # Financial News
    'Yahoo Finance': ('https://finance.yahoo.com/news/rssindex', 'Financial News'),
    'Investopedia': ('https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline', 'Financial News'),
    'CNBC Top News': ('https://www.cnbc.com/id/100003114/device/rss/rss.html', 'Financial News'),
    'MarketWatch': ('https://www.marketwatch.com/rss/topstories', 'Financial News'),

    # Macro News
    ' CNBC Economy': ('https://www.cnbc.com/id/20910258/device/rss/rss.html', 'Macro News'),
}

def get_clean_news():
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(hours=24)
    articles = []
    seen_links = set()
    seen_titles = set()

    for source, (url, tag) in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            print(f"[INFO] Parsed {len(feed.entries)} entries from {source}")
            for entry in feed.entries:
                try:
                    pub_date = None
                    if hasattr(entry, 'published_parsed'):
                        pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    elif hasattr(entry, 'updated_parsed'):
                        pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                    if not pub_date or pub_date < twenty_four_hours_ago:
                        continue

                    link = entry.get('link', '').strip()
                    title = clean_text(entry.get('title', '')).strip()

                    if not link or not title:
                        continue
                    if link in seen_links or title in seen_titles:
                        continue

                    seen_links.add(link)
                    seen_titles.add(title)

                    # Get summary or fallback to title
                    description = ''
                    if 'content' in entry and isinstance(entry.content, list) and entry.content:
                        description = entry.content[0].value
                    elif 'summary' in entry:
                        description = entry.summary

                    clean_desc = truncate(clean_text(description)) if description else title
                                    
                    # Fallback if description is still missing
                    if not clean_desc.strip():
                        clean_desc = title
                    
                    # Sentiment only if clean_desc has value
                    if not clean_desc.strip():
                        sentiment = 'Unknown'
                    else:
                        sentiment = get_sentiment_label(clean_desc)

                    articles.append({
                        'tag': tag,
                        'title': title,
                        'description': clean_desc,
                        'sentiment': sentiment,
                        'date': pub_date.date().isoformat(),  # Only date part: YYYY-MM-DD
                        'source': source,
                        'link': link
                    })
                except Exception as e:
                    print(f"[WARN] Error processing entry from {source}: {e}")
        except Exception as e:
            print(f"[ERROR] Failed to parse feed from {source}: {e}")

    return sorted(articles, key=lambda x: x['date'], reverse=True)

@app.route('/api/news', methods=['GET'])
@cache.cached()
def news():
    return jsonify(get_clean_news())

if __name__ == '__main__':
    cache.init_app(app)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
