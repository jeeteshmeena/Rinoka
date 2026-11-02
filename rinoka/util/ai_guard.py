"""Rinoka AI Guard: the detection brain behind the AI Shield plugin.

Three layers, cheapest first:

1. Local rules: fast normalisation (fancy fonts, l33t speak, dotted letters,
   zero-width tricks) and English/Hindi/Hinglish patterns for sexual content,
   scams and malware bait. Free and instant.
2. Local vision model: NudeNet (ONNX, runs on the VPS CPU) scores photos,
   stickers and video thumbnails for nudity. Free and unlimited.
3. Cloud checks, only when needed: Google Safe Browsing for links and Google
   Gemini (free tier) to judge anything the local layers find borderline,
   including new scam styles and images the local model is unsure about.
"""

import asyncio
import base64
import hashlib
import ipaddress
import json
import logging
import re
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

log = logging.getLogger("ai_guard")

SEVERE = {"sexual", "csam", "malware", "phishing"}
CATEGORIES = {"safe", "sexual", "csam", "scam", "malware", "phishing", "hate", "spam"}


@dataclass
class Verdict:
    category: str = "safe"
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    source: str = "rules"

    @property
    def flagged(self) -> bool:
        return self.category != "safe"

    @property
    def severe(self) -> bool:
        return self.category in SEVERE

    def merge(self, other: "Verdict") -> "Verdict":
        if other.score > self.score or (other.severe and not self.severe and other.score >= self.score - 0.1):
            return other
        return self


# ---------------------------------------------------------------- normalise
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "i"})
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060-\u2064\ufeff\u00ad]")
_SPACED = re.compile(r"\b(?:[a-z][\s\.\-_*]){2,}[a-z]\b")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text).lower()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.translate(_LEET)
    # p.o.r.n / p o r n / s-e-x -> porn / sex
    text = _SPACED.sub(lambda m: re.sub(r"[\s\.\-_*]", "", m.group(0)), text)
    return re.sub(r"(.)\1{2,}", r"\1\1", text)  # sexxxxy -> sexxy


def _rx(words: List[str]) -> re.Pattern:
    return re.compile(r"(?<![a-z])(?:" + "|".join(words) + r")(?![a-z])", re.I)


SEXUAL_STRONG = _rx([
    r"porn\w*", r"xxx+", r"nudes?", r"nudity", r"sex\s?chat", r"sexting", r"blow\s?job", r"hand\s?job",
    r"pussy", r"dick\s?pic\w*", r"cock", r"boobs?", r"tits", r"onlyfans", r"only\s?fans", r"fansly",
    r"escorts?", r"call\s?girls?", r"hookup", r"camgirl\w*", r"strip\s?chat", r"xvideos?", r"xhamster",
    r"pornhub", r"brazzers", r"desi\s?mms", r"viral\s?mms", r"leak(?:ed)?\s?(?:video|mms|pics?)",
    r"chudai", r"chut", r"lund", r"randi", r"nangi", r"nanga", r"bhabhi\s?(?:sex|nangi|video)",
    r"sexy\s?(?:video|vid|pics?|girl|bhabhi|aunty)", r"hot\s?(?:video|vid|pics?)\s?(?:dm|link|inbox)",
    r"full\s?open\s?(?:video|call|show)", r"video\s?call\s?service", r"paid\s?(?:service|vc|video\s?call)",
    r"(?:dm|inbox|msg)\s?(?:for|me\s?for)\s?(?:fun|service|vc|nudes?|video)", r"18\+\s?(?:video|group|link|content)",
])
SEXUAL_WEAK = _rx([r"sexy", r"hot\s?girl\w*", r"horny", r"18\+", r"adult", r"naughty", r"bold\s?video", r"romance\s?video", r"kiss\w*", r"bhabhi", r"aunty"])
CSAM = _rx([r"child\s?porn\w*", r"\bcp\s?(?:video|link|group|sell)", r"pedo\w*", r"(?:teen|minor|school\s?girl|underage)\w*\s?(?:porn|sex|nudes?|mms|video)"])
SCAM = _rx([
    r"free\s?(?:telegram\s?)?premium", r"claim\s?(?:your\s?)?(?:reward|prize|gift)", r"airdrop", r"double\s?your\s?(?:money|crypto|btc)",
    r"guaranteed\s?(?:profit|returns?)", r"(?:daily|per\s?day)\s?(?:income|earning|profit)", r"earn\s?(?:rs\.?|₹|\$)\s?\d+",
    r"work\s?from\s?home\s?(?:job|earn)", r"investment\s?plan", r"crypto\s?(?:signals?|giveaway)", r"recover\s?(?:your\s?)?account",
    r"(?:your\s?)?account\s?(?:will\s?be|is)\s?(?:banned|blocked|deleted|suspended)", r"verify\s?(?:your\s?)?account",
    r"send\s?(?:me\s?)?(?:the\s?)?otp", r"otp\s?(?:bhejo|send|share)", r"login\s?(?:code|here)", r"telegram\s?(?:support|security)\s?team",
    r"lottery", r"kbc\s?(?:lottery|winner)", r"satta", r"aviator\s?(?:predictor|hack)", r"color\s?prediction", r"betting\s?tips?",
    r"instant\s?loan", r"loan\s?app", r"mod\s?apk", r"hack(?:ed)?\s?(?:apk|app|tool)", r"paise?\s?double",
])
MALWARE_BAIT = re.compile(r"\.(?:apk|xapk|exe|scr|bat|cmd|msi|vbs|js|jar|ps1|lnk|iso|img)(?:\b|$)", re.I)


def score_text(text: str) -> Verdict:
    if not text:
        return Verdict()
    norm = normalise(text)
    if CSAM.search(norm):
        return Verdict("csam", 1.0, ["child-abuse wording"])
    strong = SEXUAL_STRONG.findall(norm)
    weak = SEXUAL_WEAK.findall(norm)
    scam = SCAM.findall(norm)
    v = Verdict()
    if strong:
        v = v.merge(Verdict("sexual", min(1.0, 0.75 + 0.1 * len(strong)), [f"sexual: {', '.join(sorted(set(strong))[:3])}"]))
    elif weak:
        v = v.merge(Verdict("sexual", min(0.6, 0.3 + 0.15 * len(weak)), [f"suggestive: {', '.join(sorted(set(weak))[:3])}"]))
    if scam:
        v = v.merge(Verdict("scam", min(1.0, 0.6 + 0.15 * len(scam)), [f"scam: {', '.join(sorted(set(scam))[:3])}"]))
    if MALWARE_BAIT.search(norm):
        v = v.merge(Verdict("malware", 0.8, ["executable / APK bait"]))
    return v


# ---------------------------------------------------------------- links
URL_RE = re.compile(r"(?i)\b((?:https?://|www\.)[^\s<>\"']+|(?:[a-z0-9-]+\.)+(?:[a-z]{2,24})(?:/[^\s<>\"']*)?)")
SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "rb.gy", "shorturl.at", "ow.ly", "buff.ly",
    "rebrand.ly", "tiny.cc", "s.id", "v.gd", "shrtco.de", "gg.gg", "linktr.ee", "bit.do", "rebrandly.com", "urlz.fr",
}
RISKY_TLDS = {
    "zip", "mov", "xyz", "top", "click", "tk", "ml", "ga", "cf", "gq", "work", "loan", "rest", "cam", "sbs", "cfd",
    "icu", "buzz", "monster", "quest", "lol", "bond", "live", "fun", "online", "site", "shop", "win", "bid", "xxx", "sex", "porn", "adult",
}
ADULT_HOST = re.compile(r"porn|xxx|xvideo|xhamster|xnxx|redtube|youporn|onlyfans|fansly|chaturbate|stripchat|camsoda|brazzers|spankbang|nude|sex(?!tant)|desi.?mms|hentai|rule34|eporner|motherless", re.I)
BRAND_LOOKALIKE = re.compile(r"telegr[a4]m(?!\.org$)|teleqram|telegrarn|tg-?premium|t-me\.|whatsap+|paytm-|phonepe-|sbi-?(?:kyc|bank)|amaz0n|g00gle|paypa1|binance-|metamask-|trustwallet-", re.I)
TRUSTED = {
    "t.me", "telegram.org", "telegram.me", "telegra.ph", "google.com", "youtube.com", "youtu.be", "wikipedia.org", "github.com",
    "instagram.com", "x.com", "twitter.com", "facebook.com", "linkedin.com", "reddit.com", "amazon.in", "amazon.com", "flipkart.com",
}


def extract_urls(text: str, entity_urls: Optional[List[str]] = None) -> List[str]:
    urls = list(entity_urls or [])
    for m in URL_RE.finditer(text or ""):
        u = m.group(1).rstrip(").,!?:;")
        if "." in u and not re.fullmatch(r"[\d.]+", u):
            urls.append(u)
    seen, out = set(), []
    for u in urls:
        if not u.lower().startswith(("http://", "https://")):
            u = "http://" + u
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:10]


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _registered(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def score_url(url: str) -> Verdict:
    host = host_of(url)
    if not host:
        return Verdict()
    if host in TRUSTED or _registered(host) in TRUSTED:
        path = urlparse(url).path.lower()
        if host in {"t.me", "telegram.me"} and re.search(r"porn|xxx|nude|mms|18|sexy|desi|leak", path):
            return Verdict("sexual", 0.85, [f"adult Telegram link: {host}{path[:30]}"], "links")
        return Verdict()
    reasons: List[str] = []
    score, category = 0.0, "phishing"
    if ADULT_HOST.search(host) or ADULT_HOST.search(urlparse(url).path):
        return Verdict("sexual", 0.95, [f"adult site: {host}"], "links")
    try:
        ipaddress.ip_address(host)
        score += 0.5
        reasons.append("raw IP address link")
    except ValueError:
        pass
    if host.startswith("xn--") or ".xn--" in host:
        score += 0.5
        reasons.append("punycode look-alike domain")
    if BRAND_LOOKALIKE.search(host):
        score += 0.6
        reasons.append(f"fake brand domain: {host}")
    tld = host.rsplit(".", 1)[-1]
    if tld in RISKY_TLDS:
        score += 0.25
        reasons.append(f"risky .{tld} domain")
    if MALWARE_BAIT.search(urlparse(url).path):
        score += 0.6
        category = "malware"
        reasons.append("direct APK/EXE download")
    if re.search(r"(login|verify|wallet|airdrop|claim|bonus|gift|premium|otp|kyc|recover)", url, re.I):
        score += 0.25
        reasons.append("credential/reward bait in URL")
    if host.count("-") >= 3 or len(host) > 40:
        score += 0.15
        reasons.append("unusual domain shape")
    if host in SHORTENERS:
        score += 0.2
        reasons.append("hidden behind a URL shortener")
    if score < 0.3:
        return Verdict()
    return Verdict(category, min(score, 1.0), reasons, "links")


# ---------------------------------------------------------------- cache / budget
class TTLCache:
    def __init__(self, size: int = 5000, ttl: float = 6 * 3600) -> None:
        self.size, self.ttl = size, ttl
        self.data: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()

    def get(self, key: str) -> Any:
        item = self.data.get(key)
        if not item or item[0] < time.time():
            return None
        self.data.move_to_end(key)
        return item[1]

    def set(self, key: str, value: Any) -> None:
        self.data[key] = (time.time() + self.ttl, value)
        self.data.move_to_end(key)
        while len(self.data) > self.size:
            self.data.popitem(last=False)


class RateBudget:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.calls: List[float] = []

    def take(self) -> bool:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < 60]
        if len(self.calls) >= self.per_minute:
            return False
        self.calls.append(now)
        return True


# ---------------------------------------------------------------- the guard
GEMINI_PROMPT = """You are the moderation brain of a Telegram group bot used mostly in India.
Messages can be in English, Hindi, Hinglish or use tricks (fancy fonts, emojis, spacing, code words).
Classify the user content. Categories:
- sexual: porn, nudity, sexual services, sexting offers, adult links, sex-chat/video-call selling, explicit or highly sexual imagery
- csam: anything sexual involving minors
- scam: fake earning/investment/loan/betting offers, fake giveaways, account-recovery or OTP tricks, impersonating Telegram/banks
- phishing: links or text trying to steal logins, OTPs, wallets, or pretending to be an official site
- malware: APK/EXE/mod app downloads, "hack" tools, suspicious file links
- hate: severe abuse, threats or hate against a group
- spam: unsolicited promotion or channel/group advertising
- safe: everything else, including normal chat, jokes, mild flirting, news and medical/educational talk
Be strict on sexual, csam, scam, phishing and malware. Do not flag normal conversation.
Answer ONLY with JSON: {"category": "<one of the above>", "confidence": <0..1>, "reason": "<short reason in English>"}"""


class AIGuard:
    def __init__(self, http: aiohttp.ClientSession, *, gemini_key: Optional[str], gemini_model: str,
                 safe_browsing_key: Optional[str], local_model: bool, gemini_rpm: int = 12) -> None:
        self.http = http
        self.gemini_key = gemini_key
        self.gemini_model = gemini_model
        self.sb_key = safe_browsing_key
        self.local_model_enabled = local_model
        self._detector: Any = None
        self._detector_failed = False
        self._detector_lock = asyncio.Lock()
        self.cache = TTLCache()
        self.gemini_budget = RateBudget(gemini_rpm)
        self.gemini_sem = asyncio.Semaphore(3)

    # ---- links
    async def expand(self, url: str) -> str:
        if host_of(url) not in SHORTENERS:
            return url
        try:
            async with self.http.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=4)) as r:
                return str(r.url)
        except Exception:  # skipcq: PYL-W0703
            return url

    async def safe_browsing(self, urls: List[str]) -> Optional[Verdict]:
        if not self.sb_key or not urls:
            return None
        body = {
            "client": {"clientId": "rinoka-bot", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": u} for u in urls],
            },
        }
        try:
            async with self.http.post(
                f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={self.sb_key}",
                json=body, timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                data = await r.json(content_type=None)
        except Exception as err:  # skipcq: PYL-W0703
            log.debug("Safe Browsing error: %s", err)
            return None
        matches = data.get("matches") or []
        if not matches:
            return None
        kind = matches[0].get("threatType", "")
        category = "phishing" if kind == "SOCIAL_ENGINEERING" else "malware"
        return Verdict(category, 1.0, [f"Google Safe Browsing: {kind.lower()} ({host_of(matches[0]['threat']['url'])})"], "safebrowsing")

    async def check_links(self, urls: List[str], allow: Optional[List[str]] = None) -> Verdict:
        allow = allow or []
        urls = [u for u in urls if host_of(u) not in allow and _registered(host_of(u)) not in allow]
        if not urls:
            return Verdict()
        expanded = await asyncio.gather(*(self.expand(u) for u in urls))
        verdict = Verdict()
        for u in expanded:
            verdict = verdict.merge(score_url(u))
        sb = await self.safe_browsing(list(expanded))
        if sb:
            verdict = verdict.merge(sb)
        return verdict

    # ---- gemini
    async def gemini(self, text: str = "", image: Optional[bytes] = None, mime: str = "image/jpeg") -> Optional[Verdict]:
        if not self.gemini_key or (not text and not image):
            return None
        key = "g:" + hashlib.sha1((text or "").encode() + (image or b"")).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if not self.gemini_budget.take():
            log.debug("Gemini budget exhausted, skipping")
            return None
        parts: List[Dict[str, Any]] = [{"text": GEMINI_PROMPT}]
        if text:
            parts.append({"text": "Content to classify:\n" + text[:3000]})
        if image:
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode()}})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 120},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"
        try:
            async with self.gemini_sem, self.http.post(
                url, json=body, headers={"x-goog-api-key": self.gemini_key}, timeout=aiohttp.ClientTimeout(total=12)
            ) as r:
                data = await r.json(content_type=None)
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            res = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except Exception as err:  # skipcq: PYL-W0703
            log.debug("Gemini error: %s", err)
            return None
        cat = str(res.get("category", "safe")).lower()
        cat = cat if cat in CATEGORIES else "safe"
        conf = float(res.get("confidence", 0) or 0)
        verdict = Verdict(cat, conf if cat != "safe" else 0.0, [f"AI: {res.get('reason', cat)}"[:160]], "gemini")
        self.cache.set(key, verdict)
        return verdict

    # ---- images
    async def _load_detector(self) -> Any:
        if self._detector or self._detector_failed or not self.local_model_enabled:
            return self._detector
        async with self._detector_lock:
            if self._detector is None and not self._detector_failed:
                try:
                    from nudenet import NudeDetector  # type: ignore

                    self._detector = await asyncio.get_running_loop().run_in_executor(None, NudeDetector)
                    log.info("NudeNet model loaded")
                except Exception as err:  # skipcq: PYL-W0703
                    self._detector_failed = True
                    log.warning("NudeNet unavailable (%s); image checks will use Gemini only", err)
        return self._detector

    EXPLICIT = {"FEMALE_GENITALIA_EXPOSED": 1.0, "MALE_GENITALIA_EXPOSED": 1.0, "ANUS_EXPOSED": 1.0,
                "FEMALE_BREAST_EXPOSED": 0.9, "BUTTOCKS_EXPOSED": 0.7}
    SUGGESTIVE = {"FEMALE_GENITALIA_COVERED": 0.35, "FEMALE_BREAST_COVERED": 0.2, "BUTTOCKS_COVERED": 0.2}

    async def check_image(self, image: bytes, *, unique_id: Optional[str] = None, threshold: float = 0.55,
                          mime: str = "image/jpeg") -> Verdict:
        key = f"img:{unique_id or hashlib.sha1(image).hexdigest()}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        verdict = Verdict()
        detector = await self._load_detector()
        if detector:
            try:
                dets = await asyncio.get_running_loop().run_in_executor(None, detector.detect, image)
            except Exception as err:  # skipcq: PYL-W0703
                log.debug("NudeNet failed: %s", err)
                dets = []
            best, label = 0.0, ""
            for d in dets or []:
                weight = self.EXPLICIT.get(d.get("class", ""), 0) or self.SUGGESTIVE.get(d.get("class", ""), 0)
                s = float(d.get("score", 0)) * weight
                if s > best:
                    best, label = s, d.get("class", "")
            if best >= threshold:
                verdict = Verdict("sexual", best, [f"nudity detected ({label.lower().replace('_', ' ')})"], "vision")
            elif best >= threshold * 0.5:
                # borderline: let Gemini decide when available
                ai = await self.gemini(image=image, mime=mime)
                if ai and ai.flagged and ai.score >= 0.6:
                    verdict = ai
        else:
            ai = await self.gemini(image=image, mime=mime)
            if ai and ai.flagged and ai.score >= 0.6:
                verdict = ai
        self.cache.set(key, verdict)
        return verdict

    # ---- text (rules + optional AI)
    async def check_text(self, text: str, *, sensitivity: float, use_ai: bool, force_ai: bool = False) -> Verdict:
        local = score_text(text)
        if local.category == "csam" or local.score >= 0.85:
            return local
        if use_ai and (local.score >= 0.25 or extract_urls(text) or (force_ai and len(text) > 12)):
            ai = await self.gemini(text=text)
            if ai and ai.flagged and ai.score >= sensitivity:
                return ai if ai.score >= local.score else local
            if ai and not ai.flagged and local.score < 0.75:
                return Verdict()  # AI says it is fine; trust it for borderline local hits
        return local if local.score >= sensitivity else Verdict()
