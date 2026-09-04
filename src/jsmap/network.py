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
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

from typing import Any, Dict, List, Optional, Union

def build_session(
    args: Any = None,
    url: Optional[str] = None,
    proxy: Optional[str] = None,
    no_verify: bool = False,
    cookie: Optional[str] = None,
    header: Optional[Union[List[str], Dict[str, str]]] = None,
) -> requests.Session:
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
    
    eff_url = getattr(args, "url", None) or url
    if eff_url:
        headers["Referer"] = eff_url
    session.headers.update(headers)

    eff_proxy = getattr(args, "proxy", None) or proxy
    if eff_proxy:
        session.proxies = {"http": eff_proxy, "https": eff_proxy}

    eff_no_verify = getattr(args, "no_verify", False) or no_verify
    if eff_no_verify:
        session.verify = False
        urllib3.disable_warnings()

    eff_cookie = getattr(args, "cookie", None) or cookie
    if eff_cookie:
        session.headers.update({"Cookie": eff_cookie})

    eff_header = getattr(args, "header", None) or header
    if eff_header:
        if isinstance(eff_header, dict):
            session.headers.update(eff_header)
        else:
            for hdr in eff_header:
                k, _, v = hdr.partition(":")
                session.headers.update({k.strip(): v.strip()})
    return session
