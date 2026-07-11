import requests
import urllib3
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def build_session(args) -> requests.Session:
    session = requests.Session()
    
    # OPSEC: Add retry logic with exponential backoff for WAFs / throttling
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    headers = {**DEFAULT_HEADERS}
    
    # OPSEC: Randomize User-Agent
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/123.0.0.0 Safari/537.36"
    ]
    headers["User-Agent"] = random.choice(user_agents)
    
    if hasattr(args, "url") and args.url:
        headers["Referer"] = args.url
    session.headers.update(headers)
    if getattr(args, "proxy", None):
        session.proxies = {"http": args.proxy, "https": args.proxy}
    if getattr(args, "no_verify", False):
        session.verify = False
        urllib3.disable_warnings()
    if getattr(args, "cookie", None):
        session.headers.update({"Cookie": args.cookie})
    if getattr(args, "header", None):
        for hdr in args.header:
            k, _, v = hdr.partition(":")
            session.headers.update({k.strip(): v.strip()})
    return session
