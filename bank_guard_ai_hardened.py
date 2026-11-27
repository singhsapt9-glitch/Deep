"""Bank Guard AI - privacy-first hardened prototype.

Important security boundaries:
- Statement bytes are parsed locally. Raw descriptions, dates and amounts are NEVER
  sent to Hugging Face by this application.
- External AI is optional and OFF by default. With explicit opt-in, only a small
  aggregate of fixed category labels and counts is sent.
- Gradio's own upload cache is periodically cleaned with Blocks(delete_cache=...).
  Python cannot guarantee zero traces in RAM, swap, filesystem snapshots or SSDs.
- The in-memory rate limiter is for a single-process prototype only. Use Redis and
  authenticated identities for multi-worker/public deployments.
- PDF parsing should be isolated in a resource-limited worker/container for public use.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Optional

import gradio as gr
import numpy as np
import pandas as pd
import pdfplumber
from huggingface_hub import InferenceClient


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_TITLE = "Bank Guard AI"
MODEL = os.getenv("BG_HF_MODEL", "openai/gpt-oss-120b")
SHARE = False  # Deliberately never create a public Gradio share link.

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_CELL_CHARS = 2_048
MAX_DESCRIPTION_CHARS = 2_048
MAX_FLAGGED_ROWS = 500

RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_SECONDS = 10 * 60
GLOBAL_RATE_LIMIT_MAX = 30

HF_TIMEOUT_SECONDS = 25
HF_MAX_TOKENS = 650
LLM_CONCURRENCY = 2

ESPEAK_BIN = shutil.which("espeak-ng")
AUDIO_TIMEOUT_SECONDS = 12
MAX_AUDIO_TEXT_CHARS = 550

logging.basicConfig(
    level=os.getenv("BG_LOG_LEVEL", "WARNING"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bank_guard_ai")


class StatementError(Exception):
    """A safe, user-displayable validation or processing error."""


def _get_hf_token() -> Optional[str]:
    """Read the token from environment or Colab Secrets; never print it."""
    token = os.getenv("HF_TOKEN")
    if token:
        return token
    try:
        from google.colab import userdata  # type: ignore

        return userdata.get("HF_TOKEN")
    except Exception:
        return None


_HF_TOKEN = _get_hf_token()
_HF_CLIENT: Optional[InferenceClient] = None
if _HF_TOKEN:
    try:
        _HF_CLIENT = InferenceClient(
            model=MODEL,
            token=_HF_TOKEN,
            timeout=HF_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # Do not log exception text; it may contain request metadata.
        logger.warning("Hugging Face client initialization failed: %s", type(exc).__name__)
        _HF_CLIENT = None


# ---------------------------------------------------------------------------
# Request limiting (single process only)
# ---------------------------------------------------------------------------
_RATE_LOCK = threading.Lock()
_RATE_LOG: dict[str, deque[float]] = defaultdict(deque)
_GLOBAL_RATE_LOG: deque[float] = deque()
_LLM_SEMAPHORE = threading.BoundedSemaphore(LLM_CONCURRENCY)


def _session_id(request: Optional[gr.Request]) -> str:
    value = getattr(request, "session_hash", None) if request is not None else None
    return str(value or "anonymous")[:128]


def check_rate_limit(session_id: str) -> bool:
    """Per-session and global sliding-window limit for this Python process."""
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    with _RATE_LOCK:
        while _GLOBAL_RATE_LOG and _GLOBAL_RATE_LOG[0] <= cutoff:
            _GLOBAL_RATE_LOG.popleft()

        history = _RATE_LOG[session_id]
        while history and history[0] <= cutoff:
            history.popleft()

        if len(history) >= RATE_LIMIT_MAX:
            return False
        if len(_GLOBAL_RATE_LOG) >= GLOBAL_RATE_LIMIT_MAX:
            return False

        history.append(now)
        _GLOBAL_RATE_LOG.append(now)

        # Bound stale session-key growth.
        for key in list(_RATE_LOG):
            if not _RATE_LOG[key]:
                _RATE_LOG.pop(key, None)

        return True


def on_leave(request: gr.Request = None) -> None:
    """Drop per-session rate-limit state when the Gradio tab disconnects."""
    sid = _session_id(request)
    with _RATE_LOCK:
        _RATE_LOG.pop(sid, None)


# ---------------------------------------------------------------------------
# File validation and local parsing
# ---------------------------------------------------------------------------
DESC_NAMES = (
    "description",
    "narration",
    "particulars",
    "remarks",
    "details",
    "transaction remarks",
)
DEBIT_NAMES = (
    "debit",
    "withdrawal",
    "withdrawals",
    "withdrawal amt",
    "debit amount",
    "dr",
)


def validate_upload(data: object) -> bytes:
    """Validate the bytes received from gr.File(type='binary')."""
    if not isinstance(data, (bytes, bytearray)):
        raise StatementError("ਕਿਰਪਾ ਕਰਕੇ PDF ਜਾਂ CSV ਫਾਈਲ upload ਕਰੋ।")

    raw = bytes(data)
    if not raw:
        raise StatementError("ਫਾਈਲ ਖਾਲੀ ਹੈ।")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise StatementError("ਫਾਈਲ 10 MB ਤੋਂ ਵੱਡੀ ਹੈ।")

    # Strict PDF signature check. Non-PDF files are considered CSV only after
    # rejecting NUL bytes and validating that a text parser can read them.
    if raw.startswith(b"%PDF-"):
        return raw
    if b"\x00" in raw[: min(len(raw), 4096)]:
        raise StatementError("ਫਾਈਲ ਦਾ format ਸਹੀ ਨਹੀਂ ਹੈ।")
    return raw


def _find_col(columns, names):
    normalized = [(col, str(col).strip().lower()) for col in columns]
    for original, lowered in normalized:
        if lowered in names:
            return original
    for original, lowered in normalized:
        if any(name in lowered for name in names if len(name) > 3):
            return original
    return None


def _parse_amount(value: object) -> float:
    """Parse a debit value while preserving minus signs and parenthesized negatives."""
    raw = str(value).strip()
    if raw.lower() in {"", "-", "—", "–", "na", "n/a", "nan", "none"}:
        return 0.0

    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]

    raw = re.sub(r"(?i)(?<![A-Z])(?:INR|RS\.?|DR\.?|CR\.?)(?![A-Z])", "", raw)
    raw = raw.replace("₹", "").replace(",", "").replace(" ", "")

    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", raw):
        raise StatementError("Debit ਕਾਲਮ ਵਿੱਚ ਅਣਪਛਾਤੀ ਰਕਮ ਮਿਲੀ ਹੈ।")

    amount = float(raw)
    if not math.isfinite(amount):
        raise StatementError("Debit ਕਾਲਮ ਵਿੱਚ ਗਲਤ ਰਕਮ ਮਿਲੀ ਹੈ।")
    if negative:
        amount = -abs(amount)
    return amount


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise StatementError("ਸਟੇਟਮੈਂਟ ਵਿੱਚ ਕੋਈ transaction row ਨਹੀਂ ਹੈ।")
    if len(frame.columns) > MAX_COLUMNS:
        raise StatementError("ਫਾਈਲ ਵਿੱਚ ਬਹੁਤ ਜ਼ਿਆਦਾ columns ਹਨ।")

    desc_col = _find_col(frame.columns, DESC_NAMES)
    debit_col = _find_col(frame.columns, DEBIT_NAMES)
    date_col = _find_col(frame.columns, ("date",))

    if desc_col is None or debit_col is None:
        raise StatementError(
            "Description ਅਤੇ Debit ਕਾਲਮ ਨਹੀਂ ਮਿਲੇ। ਬੈਂਕ statement ਦਾ supported format ਵਰਤੋ।"
        )

    descriptions = frame[desc_col].fillna("").astype(str)
    if descriptions.str.len().gt(MAX_DESCRIPTION_CHARS).any():
        raise StatementError("ਕਿਸੇ transaction description ਦੀ ਲੰਬਾਈ limit ਤੋਂ ਵੱਧ ਹੈ।")

    dates = (
        frame[date_col].fillna("").astype(str).str.slice(0, 64)
        if date_col is not None
        else pd.Series([""] * len(frame), index=frame.index)
    )
    amounts = frame[debit_col].map(_parse_amount)

    result = pd.DataFrame(
        {
            "Date": dates,
            "Description": descriptions.str.slice(0, MAX_DESCRIPTION_CHARS),
            "Debit": amounts,
        }
    )
    if len(result) > MAX_ROWS:
        raise StatementError("ਸਟੇਟਮੈਂਟ ਵਿੱਚ transactions ਦੀ ਗਿਣਤੀ limit ਤੋਂ ਵੱਧ ਹੈ।")
    return result


def extract_transactions(data: bytes) -> pd.DataFrame:
    """Parse PDF/CSV from memory; no user-provided filesystem path is accepted."""
    raw = validate_upload(data)

    if raw.startswith(b"%PDF-"):
        frames: list[pd.DataFrame] = []
        last_header: Optional[list[str]] = None
        rows_seen = 0
        try:
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                if len(pdf.pages) > MAX_PDF_PAGES:
                    raise StatementError(
                        f"PDF ਵਿੱਚ {MAX_PDF_PAGES} ਤੋਂ ਵੱਧ pages ਹਨ।"
                    )

                for page in pdf.pages:
                    tables = page.extract_tables() or []
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        rows_seen += len(table)
                        if rows_seen > MAX_ROWS + MAX_PDF_PAGES:
                            raise StatementError("PDF ਵਿੱਚ ਬਹੁਤ ਜ਼ਿਆਦਾ transaction rows ਹਨ।")

                        header = [str(cell or "")[:MAX_CELL_CHARS] for cell in table[0]]
                        candidate = None
                        try:
                            candidate = _normalize(
                                pd.DataFrame(table[1:], columns=header)
                            )
                            last_header = header
                        except (StatementError, ValueError):
                            if last_header and len(table[0]) == len(last_header):
                                candidate = _normalize(
                                    pd.DataFrame(table, columns=last_header)
                                )
                        if candidate is not None and not candidate.empty:
                            frames.append(candidate)
                            if sum(len(item) for item in frames) > MAX_ROWS:
                                raise StatementError("PDF ਵਿੱਚ ਬਹੁਤ ਜ਼ਿਆਦਾ transactions ਹਨ।")
        except StatementError:
            raise
        except Exception as exc:
            logger.warning("PDF parsing failed: %s", type(exc).__name__)
            raise StatementError("PDF ਪੜ੍ਹੀ ਨਹੀਂ ਜਾ ਸਕੀ। File encrypted ਜਾਂ malformed ਹੋ ਸਕਦੀ ਹੈ।") from None

        if not frames:
            raise StatementError("PDF ਵਿੱਚ supported transaction table ਨਹੀਂ ਮਿਲੀ।")
        return pd.concat(frames, ignore_index=True).head(MAX_ROWS)

    # CSV parsing: try UTF-8 BOM first, then Windows-1252 for common bank exports.
    if b"\x00" in raw:
        raise StatementError("CSV ਵਿੱਚ invalid binary characters ਹਨ।")

    last_error = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            frame = pd.read_csv(
                io.BytesIO(raw),
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
                nrows=MAX_ROWS + 1,
                on_bad_lines="error",
            )
            if frame.shape[1] > MAX_COLUMNS:
                raise StatementError("CSV ਵਿੱਚ ਬਹੁਤ ਜ਼ਿਆਦਾ columns ਹਨ।")
            if len(frame) > MAX_ROWS:
                raise StatementError("CSV ਵਿੱਚ ਬਹੁਤ ਜ਼ਿਆਦਾ rows ਹਨ।")
            for column in frame.columns:
                if frame[column].astype(str).str.len().gt(MAX_CELL_CHARS).any():
                    raise StatementError("CSV ਵਿੱਚ ਬਹੁਤ ਵੱਡਾ cell ਮਿਲਿਆ ਹੈ।")
            return _normalize(frame)
        except StatementError:
            raise
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            logger.warning("CSV parsing failed: %s", type(exc).__name__)
            raise StatementError("CSV ਪੜ੍ਹੀ ਨਹੀਂ ਜਾ ਸਕੀ। Header ਅਤੇ rows ਚੈੱਕ ਕਰੋ।") from None

    logger.warning("CSV encoding could not be detected: %s", type(last_error).__name__ if last_error else "unknown")
    raise StatementError("CSV ਦੀ text encoding support ਨਹੀਂ ਹੈ। UTF-8 CSV export ਕਰੋ।")


# ---------------------------------------------------------------------------
# Local classification. Raw descriptions never leave this process.
# ---------------------------------------------------------------------------
CATEGORY_RULES = (
    ("SMS_ALERT_FEE", re.compile(r"\bSMS\b.{0,30}\b(?:FEE|CHG|CHARGE)\b|\b(?:FEE|CHG|CHARGE)\b.{0,30}\bSMS\b", re.I)),
    ("MINIMUM_BALANCE_FEE", re.compile(r"\bMIN\s*BAL\w*\b|\bNON[ -]?MAINT\w*\b", re.I)),
    ("MAINTENANCE_FEE", re.compile(r"\bMAINT(?:ENANCE)?\b", re.I)),
    ("AUTO_RENEWAL", re.compile(r"\bAUTO\s*RENEW\w*\b|\bRENEW(?:AL)?\b", re.I)),
    ("GST_CHARGE", re.compile(r"\bGST\b", re.I)),
    ("MANDATE_OR_ACH", re.compile(r"\bE[ -]?MANDATE\b|\bACH\b", re.I)),
    ("BANK_FEE_OR_CHARGE", re.compile(r"\bCHG\b|\bCHARGES?\b|\bFEES?\b|\bPENALTY\b", re.I)),
)
FLAG_PATTERN = re.compile(
    r"\b(?:CHG|CHARGES?|FEES?|PENALTY|AUTO\s*RENEW\w*|RENEW(?:AL)?|"
    r"E-?MANDATE|MIN\s*BAL\w*|NON-?MAINT\w*|MAINT(?:ENANCE)?|SMS|GST|ACH)\b",
    re.IGNORECASE,
)

CATEGORY_PUNJABI = {
    "SMS_ALERT_FEE": "SMS ਅਲਰਟ ਫੀਸ",
    "MINIMUM_BALANCE_FEE": "ਘੱਟੋ-ਘੱਟ ਬੈਲੈਂਸ ਚਾਰਜ",
    "MAINTENANCE_FEE": "ਖਾਤਾ/ਕਾਰਡ ਮੈਨਟੇਨੈਂਸ ਚਾਰਜ",
    "AUTO_RENEWAL": "ਆਟੋ-ਰੀਨਿਊਅਲ ਜਾਂ ਸਬਸਕ੍ਰਿਪਸ਼ਨ",
    "GST_CHARGE": "GST ਨਾਲ ਸੰਬੰਧਿਤ ਐਂਟਰੀ",
    "MANDATE_OR_ACH": "ACH / ਮੈਨਡੇਟ ਐਂਟਰੀ",
    "BANK_FEE_OR_CHARGE": "ਬੈਂਕ ਫੀਸ ਜਾਂ ਚਾਰਜ",
    "OTHER_FLAGGED": "ਹੋਰ ਜਾਂਚ ਵਾਲੀ ਐਂਟਰੀ",
}


def classify_transaction(description: str) -> str:
    text = str(description)[:MAX_DESCRIPTION_CHARS]
    for category, pattern in CATEGORY_RULES:
        if pattern.search(text):
            return category
    return "OTHER_FLAGGED"


def select_flagged(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["Description"].str.contains(FLAG_PATTERN, na=False)
    flagged = df.loc[mask].copy()
    if len(flagged) > MAX_FLAGGED_ROWS:
        raise StatementError(
            f"{MAX_FLAGGED_ROWS} ਤੋਂ ਵੱਧ flagged entries ਹਨ। ਛੋਟੀ date range ਵਾਲੀ statement ਵਰਤੋ।"
        )
    if not flagged.empty:
        flagged["Category"] = flagged["Description"].map(classify_transaction)
    return flagged


def make_ai_aggregate(flagged: pd.DataFrame) -> list[dict[str, object]]:
    """Build only fixed category names and counts. Never add dates, amounts or text."""
    counts = Counter(flagged["Category"].tolist())
    allowed = set(CATEGORY_PUNJABI)
    return [
        {"category": name, "count": int(count)}
        for name, count in sorted(counts.items())
        if name in allowed
    ]


# ---------------------------------------------------------------------------
# Optional Hugging Face inference. The only user-derived data sent is aggregate
# counts for fixed category labels, and only after explicit checkbox opt-in.
# ---------------------------------------------------------------------------
SYSTEM_RULES = """You are Bank Guard AI, a cautious financial-information assistant.
You receive only a JSON list of fixed transaction category labels and counts.
These counts are automated flags, NOT proof of fraud, unauthorized activity,
or refund eligibility. Do not invent RBI rules, legal deadlines, bank policies,
amounts, account details, dates, names, or transaction identifiers. Do not ask
for personal or banking information. Explain the categories in Punjabi and
write a general English complaint email template with placeholders. Ask the
bank to verify the charges and applicable tariff/mandate. Use these exact
section markers:
###PUNJABI###
Punjabi explanation
###EMAIL###
General English complaint email
"""


def ask_llm_aggregate(aggregate: list[dict[str, object]]) -> Optional[str]:
    if _HF_CLIENT is None:
        return None
    if not _LLM_SEMAPHORE.acquire(blocking=False):
        return None

    try:
        # This JSON is generated entirely from hard-coded labels and integer counts.
        safe_payload = json.dumps(aggregate, ensure_ascii=True, separators=(",", ":"))
        result = _HF_CLIENT.chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_RULES},
                {"role": "user", "content": "Explain these aggregate category counts only:\n" + safe_payload},
            ],
            max_tokens=HF_MAX_TOKENS,
            temperature=0.1,
        )
        if not result.choices:
            return None
        content = result.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            return None
        return content[:8_000]
    except Exception as exc:
        # Never expose provider error strings, headers, payloads or tokens.
        logger.warning("Hugging Face inference failed: %s", type(exc).__name__)
        return None
    finally:
        _LLM_SEMAPHORE.release()


def split_sections(text: str) -> tuple[str, str]:
    if "###EMAIL###" not in text:
        return text[:5_000].strip(), ""
    before, after = text.split("###EMAIL###", 1)
    punjabi = before.replace("###PUNJABI###", "").strip()
    return punjabi[:5_000], after.strip()[:5_000]


def build_local_report(aggregate: list[dict[str, object]]) -> tuple[str, str]:
    if not aggregate:
        return "ਕੋਈ flagged category ਨਹੀਂ ਮਿਲੀ।", ""

    lines = ["ਪੰਜਾਬੀ ਵਿਸ਼ਲੇਸ਼ਣ", ""]
    for item in aggregate:
        name = str(item["category"])
        count = int(item["count"])
        lines.append(f"• {CATEGORY_PUNJABI.get(name, 'ਹੋਰ ਜਾਂਚ ਵਾਲੀ ਐਂਟਰੀ')}: {count}")
    lines.extend(
        [
            "",
            "ਇਹ ਸਿਰਫ਼ keyword-based flags ਹਨ; ਇਹ ਆਪਣੇ ਆਪ ਵਿੱਚ fraud ਜਾਂ ਗਲਤ ਕਟੌਤੀ ਦਾ ਸਬੂਤ ਨਹੀਂ।",
            "ਬੈਂਕ ਤੋਂ charge ਦਾ ਕਾਰਨ, ਲਾਗੂ tariff ਅਤੇ mandate/consent ਦੀ ਪੁਸ਼ਟੀ ਲਵੋ।",
            "",
            "ENGLISH COMPLAINT EMAIL TEMPLATE",
            "Subject: Request to review debit charges in my account",
            "",
            "Dear Branch Manager,",
            "Please review the debit entries I have identified in my bank statement.",
            "Kindly confirm the description, applicable tariff, and any mandate or consent",
            "associated with these entries. If any debit is found to be incorrect or not",
            "authorized, please explain the dispute and reversal process under the applicable",
            "bank terms and regulatory directions.",
            "",
            "Regards,",
            "[Your name]",
            "[Last four digits of account number, only if the bank requires it]",
        ]
    )
    return "\n".join(lines), "\n".join(lines[: max(2, len(aggregate) + 2)])


# ---------------------------------------------------------------------------
# Local-only offline Punjabi TTS
# ---------------------------------------------------------------------------
def text_to_punjabi_audio_offline(text: str):
    """Return an in-memory (sample_rate, ndarray) tuple; remove the temporary WAV."""
    if not ESPEAK_BIN or not text:
        return None

    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", str(text))
    clean = re.sub(r"[#*`_]", "", clean)[:MAX_AUDIO_TEXT_CHARS]
    cut = max(clean.rfind("।"), clean.rfind("."))
    if cut > 150:
        clean = clean[: cut + 1]
    if not clean.strip():
        return None

    fd, path = tempfile.mkstemp(prefix="bankguard_tts_", suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [ESPEAK_BIN, "-v", "pa", "-s", "145", "-w", path, "--stdin"],
            input=clean,
            text=True,
            encoding="utf-8",
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=AUDIO_TIMEOUT_SECONDS,
            shell=False,
            close_fds=True,
        )

        with wave.open(path, "rb") as wav:
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            frames = wav.readframes(wav.getnframes())

        dtype_by_width = {1: np.uint8, 2: np.int16, 4: np.int32}
        dtype = dtype_by_width.get(sample_width)
        if dtype is None:
            return None

        samples = np.frombuffer(frames, dtype=dtype).copy()
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
        return sample_rate, samples

    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, wave.Error, ValueError) as exc:
        logger.warning("Offline TTS failed: %s", type(exc).__name__)
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------
def run_bank_guard(
    uploaded_bytes,
    use_ai: bool,
    use_voice: bool,
    request: gr.Request = None,
):
    sid = _session_id(request)
    if not check_rate_limit(sid):
        return (
            "Rate limit reached. ਕੁਝ ਸਮੇਂ ਬਾਅਦ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
            pd.DataFrame(columns=["Date", "Category", "Debit"]),
            "",
            None,
        )

    try:
        transactions = extract_transactions(uploaded_bytes)

        flagged = select_flagged(transactions)
        if flagged.empty:
            empty = pd.DataFrame(columns=["Date", "Category", "Debit"])
            return (
                "ਕੋਈ matching charge keyword ਨਹੀਂ ਮਿਲਿਆ। ਇਹ fraud-free ਹੋਣ ਦੀ guarantee ਨਹੀਂ।",
                empty,
                "ਕੋਈ flagged entry ਨਹੀਂ ਮਿਲੀ।",
                None,
            )

        total = float(flagged["Debit"].sum())
        aggregate = make_ai_aggregate(flagged)

        # The browser gets only the date/category/amount columns, not raw descriptions.
        display_table = flagged[["Date", "Category", "Debit"]].copy()
        display_table["Category"] = display_table["Category"].map(
            lambda value: CATEGORY_PUNJABI.get(value, "ਹੋਰ ਜਾਂਚ ਵਾਲੀ ਐਂਟਰੀ")
        )

        report_text, tts_text = build_local_report(aggregate)
        ai_note = ""
        if use_ai:
            if _HF_CLIENT is None:
                ai_note = "\n\n[AI ਵਰਤਿਆ ਨਹੀਂ ਗਿਆ: HF_TOKEN configured ਨਹੀਂ। Local report ਦਿੱਤੀ ਗਈ ਹੈ.]"
            else:
                ai_response = ask_llm_aggregate(aggregate)
                if ai_response:
                    punjabi, email = split_sections(ai_response)
                    if punjabi or email:
                        report_text = (
                            "ਪੰਜਾਬੀ ਵਿਸ਼ਲੇਸ਼ਣ\n" + (punjabi or "ਉਪਲਬਧ ਨਹੀਂ")
                            + "\n\nENGLISH EMAIL TEMPLATE\n" + (email or "ਉਪਲਬਧ ਨਹੀਂ")
                        )
                        tts_text = punjabi
                    else:
                        ai_note = "\n\n[AI response ਦਾ format ਪਛਾਣਿਆ ਨਹੀਂ ਗਿਆ; local report ਦਿੱਤੀ ਗਈ ਹੈ.]"
                else:
                    ai_note = "\n\n[AI service ਉਪਲਬਧ ਨਹੀਂ; local report ਦਿੱਤੀ ਗਈ ਹੈ.]"

        report_text += ai_note
        audio = text_to_punjabi_audio_offline(tts_text) if use_voice else None

        status = (
            f"Flagged entries: {len(flagged)} | "
            f"Net amount in selected Debit column: ₹{total:,.2f} | "
            "ਇਹ automated flags ਹਨ, fraud ਦਾ ਪੱਕਾ ਸਬੂਤ ਨਹੀਂ।"
        )
        return status, display_table, report_text, audio

    except StatementError as exc:
        return (
            str(exc),
            pd.DataFrame(columns=["Date", "Category", "Debit"]),
            "",
            None,
        )
    except Exception as exc:
        # Do not include exception text or request payload in application logs.
        logger.error("Unexpected Bank Guard error: %s", type(exc).__name__)
        return (
            "ਅਣਉਮੀਦੀ ਗਲਤੀ ਆਈ। File format ਅਤੇ server logs ਚੈੱਕ ਕਰੋ।",
            pd.DataFrame(columns=["Date", "Category", "Debit"]),
            "",
            None,
        )
    finally:
        # No raw upload is written by this callback. The short-lived Gradio upload
        # cache is managed by Blocks(delete_cache=(frequency, age)).
        uploaded_bytes = None


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
with gr.Blocks(
    title=APP_TITLE,
    analytics_enabled=False,
    delete_cache=(60, 180),
) as demo:
    gr.Markdown(
        "# 🛡️ Bank Guard AI\n"
        "**Privacy-first prototype:** statement parsing and classification stay local. "
        "External AI is optional and OFF by default."
    )
    gr.Markdown(
        "⚠️ **Prototype notice:** Automated flags are not proof of fraud or refund eligibility. "
        "Do not upload statements on a public deployment until authentication, isolated PDF "
        "processing, and operational data-retention controls are configured."
    )

    file_in = gr.File(
        label="ਬੈਂਕ ਸਟੇਟਮੈਂਟ (.pdf / .csv, max 10 MB)",
        file_types=[".pdf", ".csv"],
        file_count="single",
        type="binary",
    )
    ai_opt_in = gr.Checkbox(
        label=(
            "ਮੈਂ ਸਹਿਮਤ ਹਾਂ: ਸਿਰਫ਼ aggregate category counts external Hugging Face AI ਨੂੰ ਭੇਜੇ ਜਾਣ। "
            "Dates, descriptions, account details ਅਤੇ amounts ਨਹੀਂ ਭੇਜੇ ਜਾਣਗੇ; counts ਵੀ financial behaviour ਦੱਸ ਸਕਦੇ ਹਨ।"
        ),
        value=False,
    )
    voice_chk = gr.Checkbox(label="ਆਫਲਾਈਨ ਪੰਜਾਬੀ ਆਵਾਜ਼ ਬਣਾਓ (eSpeak-NG)", value=False)
    btn = gr.Button("🔍 ਜਾਂਚ ਸ਼ੁਰੂ ਕਰੋ", variant="primary")

    out_sum = gr.Textbox(label="ਸੰਖੇਪ", lines=2, interactive=False)
    out_tab = gr.Dataframe(
        label="ਜਾਂਚ ਲਈ flagged entries (raw description ਲੁਕਾਈ ਗਈ ਹੈ)",
        interactive=False,
    )
    out_ai = gr.Textbox(label="ਵਿਸ਼ਲੇਸ਼ਣ ਅਤੇ email draft", lines=18, interactive=False)
    out_audio = gr.Audio(label="ਪੰਜਾਬੀ ਆਡੀਓ ਰਿਪੋਰਟ", type="numpy")

    btn.click(
        fn=run_bank_guard,
        inputs=[file_in, ai_opt_in, voice_chk],
        outputs=[out_sum, out_tab, out_ai, out_audio],
        concurrency_limit=2,
        api_visibility="private",
        show_progress="minimal",
    )
    demo.unload(fn=on_leave)


demo.queue(max_size=10, default_concurrency_limit=2)


def _launch() -> None:
    username = os.getenv("BG_USERNAME")
    password = os.getenv("BG_PASSWORD")
    if bool(username) != bool(password):
        raise RuntimeError("Set both BG_USERNAME and BG_PASSWORD, or neither.")

    public_deploy = os.getenv("BG_PUBLIC_DEPLOY", "0") == "1"
    if public_deploy and not (username and password):
        raise RuntimeError(
            "Public deployment refused: configure BG_USERNAME/BG_PASSWORD or use an authenticated identity proxy."
        )

    auth = (username, password) if username and password else None
    server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    is_loopback = server_name in {"127.0.0.1", "localhost", "::1"}
    if not is_loopback and not (username and password):
        raise RuntimeError(
            "Non-local bind refused: configure BG_USERNAME/BG_PASSWORD or keep GRADIO_SERVER_NAME=127.0.0.1."
        )

    demo.launch(
        share=SHARE,
        debug=False,
        show_error=False,
        max_file_size=MAX_UPLOAD_BYTES,
        max_threads=8,
        server_name=server_name,
        auth=auth,
        enable_monitoring=False,
    )


if __name__ == "__main__":
    _launch()
