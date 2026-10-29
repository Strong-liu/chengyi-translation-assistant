import logging
import re

import requests
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.translator.base_rate_limiter import BaseRateLimiter
from pdf2zh_next.translator.base_translator import BaseTranslator
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception
from tenacity import stop_after_attempt
from tenacity import wait_exponential

logger = logging.getLogger(__name__)


class BingTranslator(BaseTranslator):
    # https://github.com/immersive-translate/old-immersive-translate/blob/6df13da22664bea2f51efe5db64c63aca59c4e79/src/background/translationService.js
    name = "bing"
    lang_map = {"zh": "zh-Hans", "zh-cn": "zh-Hans", "zh-tw": "zh-Hant", "auto": "en"}

    def __init__(
        self,
        settings: SettingsModel,
        rate_limiter: BaseRateLimiter,
    ):
        super().__init__(settings, rate_limiter)
        self.session = requests.Session()
        self.endpoint = "https://www.bing.com/translator"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",  # noqa: E501
        }

    @staticmethod
    def split_text(text, max_length=1000):
        """Keep every character while respecting Bing's per-request limit."""
        chunks = []
        remaining = text
        while len(remaining) > max_length:
            window = remaining[: max_length + 1]
            sentence_breaks = list(re.finditer(r"(?<=[.!?;])\s+|\n+", window))
            if sentence_breaks and sentence_breaks[-1].end() >= max_length // 2:
                boundary = min(sentence_breaks[-1].end(), max_length)
            else:
                whitespace = list(re.finditer(r"\s+", window))
                boundary = (
                    min(whitespace[-1].end(), max_length)
                    if whitespace
                    else max_length
                )
            chunks.append(remaining[:boundary])
            remaining = remaining[boundary:]
        if remaining:
            chunks.append(remaining)
        return chunks

    def translate(self, text, ignore_cache=False, rate_limit_params=None):
        if len(text) <= 1000:
            return super().translate(text, ignore_cache, rate_limit_params)
        # Cache each safe chunk separately. Older cached long-paragraph results
        # may contain only the first 1000 input characters and must not be reused.
        translations = []
        for chunk in self.split_text(text):
            if chunk.strip():
                translations.append(
                    super().translate(chunk, ignore_cache, rate_limit_params)
                )
        return " ".join(translations)

    def find_sid(self):
        response = self.session.get(self.endpoint, headers=self.headers, timeout=45)
        response.raise_for_status()
        url = response.url[:-10]
        ig = re.findall(r"\"ig\":\"(.*?)\"", response.text)[0]
        iid = re.findall(r"data-iid=\"(.*?)\"", response.text)[-1]
        key, token = re.findall(
            r"params_AbusePreventionHelper\s=\s\[(.*?),\"(.*?)\",", response.text
        )[0]
        return url, ig, iid, key, token

    @retry(
        retry=retry_if_exception(Exception),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None):
        if len(text) > 1000:
            raise ValueError("Bing input must be split before translation")
        url, ig, iid, key, token = self.find_sid()
        response = self.session.post(
            f"{url}ttranslatev3?IG={ig}&IID={iid}",
            data={
                "fromLang": self.lang_in,
                "to": self.lang_out,
                "text": text,
                "token": token,
                "key": key,
            },
            headers=self.headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()[0]["translations"][0]["text"]
