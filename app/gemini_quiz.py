"""Google Gemini quiz generator.

Kept free of Flask routes on purpose: it takes plain values in and returns plain data (or raises
QuizGenerationError with a message that is safe to show to an admin). Nothing in here touches the
database, so an existing quiz never depends on Gemini being reachable.

Security notes
  * The API key is read from configuration (GEMINI_API_KEY in .env) and sent only in the
    `x-goog-api-key` request header, so it never appears in a URL, a log line or an error message.
  * The model's answer is treated as untrusted input: it must be JSON, every question is validated,
    and all text is stripped of markup before it is shown or stored.
"""
import json
import logging
import random
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DIFFICULTIES = ("easy", "medium", "hard")
LETTERS = ("A", "B", "C", "D")
MAX_TEXT, MAX_OPTION, MAX_EXPLANATION = 500, 200, 600
_RETRY_STATUS = {429, 500, 502, 503, 504}  # temporary problems worth one more try; 400/401/403 are not
_RETRIES = 2

PROMPT = """You are a quiz generation system.

Generate exactly {number} multiple-choice questions about:
{topic}

Difficulty:
{difficulty}

Each question must have exactly four unique options.

Return ONLY valid JSON in this structure:

{{
  "questions": [
    {{
      "question_text": "...",
      "options": {{
        "A": "...",
        "B": "...",
        "C": "...",
        "D": "..."
      }},
      "correct_answer": "A",
      "explanation": "...",
      "difficulty": "{difficulty}",
      "topic": "..."
    }}
  ]
}}

Rules:
- Exactly {number} questions.
- Exactly four options per question.
- correct_answer must be A, B, C, or D.
- Only one option can be correct.
- Do not duplicate questions.
- Do not include markdown.
- Do not include text outside the JSON.
- Questions must be factually appropriate for the requested topic and difficulty."""


class QuizGenerationError(Exception):
    """Generation failed. str(error) is a friendly message for the admin; no quiz must be created."""


def clean_text(value, limit):
    """Plain, single-line-ish text: no HTML tags, no control characters, bounded length."""
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    value = re.sub(r"[ \t]+", " ", value).strip()
    return value[:limit]


def build_prompt(topic, number, difficulty):
    return PROMPT.format(number=number, topic=topic, difficulty=difficulty.capitalize())


def _post(prompt, api_key, model, timeout):
    """One HTTP call to Gemini. Returns the model's text. Raises QuizGenerationError."""
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7,
                             "maxOutputTokens": 8192},
    }).encode()
    req = urllib.request.Request(
        API_URL.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    if data.get("promptFeedback", {}).get("blockReason"):
        raise QuizGenerationError("Gemini declined this topic. Try different wording.")
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError, AttributeError):
        raise QuizGenerationError("Gemini returned an empty answer. Please try again.") from None


def call_gemini(prompt, api_key, model, timeout):
    """Call Gemini, retrying only temporary failures (rate limit, 5xx, timeouts)."""
    last = "Gemini is not available right now. Please try again in a minute."
    for attempt in range(_RETRIES + 1):
        try:
            return _post(prompt, api_key, model, timeout)
        except QuizGenerationError:
            raise
        except urllib.error.HTTPError as e:
            # log the status only - never the request (it carries the key) or the response body
            log.warning("Gemini HTTP %s (attempt %s)", e.code, attempt + 1)
            if e.code in (400, 401, 403, 404):
                raise QuizGenerationError(
                    "Gemini rejected the request. Check GEMINI_API_KEY and GEMINI_MODEL in the server settings."
                ) from None
            if e.code == 429:
                last = "Gemini is busy (rate limit reached). Please wait a minute and try again."
            if e.code not in _RETRY_STATUS:
                break
        except (urllib.error.URLError, TimeoutError, OSError):
            log.warning("Gemini request failed or timed out (attempt %s)", attempt + 1)
            last = "Gemini did not answer in time. Please try again."
        except ValueError:  # response was not JSON at all
            log.warning("Gemini sent a non-JSON response (attempt %s)", attempt + 1)
            last = "Gemini sent an unreadable answer. Please try again."
        if attempt < _RETRIES:
            time.sleep(1.5 * (attempt + 1))
    raise QuizGenerationError(last)


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # tolerate a stray code fence
    try:
        return json.loads(text)
    except ValueError:
        raise QuizGenerationError("Gemini's answer was not valid JSON. Please try again.") from None


def _options_list(raw):
    """Accept {"A":..,"B":..,"C":..,"D":..} (as asked) or a plain list of four."""
    if isinstance(raw, dict):
        if set(raw) != set(LETTERS):
            return None
        return [raw[k] for k in LETTERS]
    if isinstance(raw, list) and len(raw) == 4:
        return list(raw)
    return None


def validate_questions(payload, number):
    """Turn Gemini's JSON into clean questions or raise. Malformed/duplicate questions are skipped;
    if fewer than `number` good ones remain the whole result is rejected (no half-built quiz)."""
    items = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise QuizGenerationError("Gemini's answer had no list of questions. Please try again.")
    good, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        text = clean_text(it.get("question_text"), MAX_TEXT)
        raw_opts = _options_list(it.get("options"))
        letter = it.get("correct_answer")
        if not text or raw_opts is None or not isinstance(letter, str) or letter.strip().upper() not in LETTERS:
            continue
        opts = [clean_text(o, MAX_OPTION) for o in raw_opts]
        if not all(opts) or len({o.casefold() for o in opts}) != 4:
            continue
        key = re.sub(r"\W+", " ", text.casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        correct = LETTERS.index(letter.strip().upper())
        good.append({"text": text, "options": opts, "correct": correct,
                     "explanation": clean_text(it.get("explanation"), MAX_EXPLANATION)})
    if len(good) < number:
        raise QuizGenerationError(
            f"Gemini returned only {len(good)} usable question(s) out of {number}. Please try again.")
    good = good[:number]
    for q in good:  # models favour certain letters; mix them, keeping the right answer marked
        right = q["options"][q["correct"]]
        random.shuffle(q["options"])
        q["correct"] = q["options"].index(right)
    return good


def generate_quiz(topic, number, difficulty, *, api_key, model, timeout, max_questions=20):
    """Public entry point. Returns {"topic","difficulty","questions":[{text,options,correct,explanation}]}."""
    topic = clean_text(topic, 200)
    difficulty = (difficulty or "").strip().lower()
    if not api_key:
        raise QuizGenerationError("AI quiz generation is not set up yet: add GEMINI_API_KEY to the server's .env file.")
    if len(topic) < 3:
        raise QuizGenerationError("Enter a topic (at least 3 characters).")
    if difficulty not in DIFFICULTIES:
        raise QuizGenerationError("Choose Easy, Medium or Hard.")
    if not isinstance(number, int) or not 1 <= number <= max_questions:
        raise QuizGenerationError(f"Choose between 1 and {max_questions} questions.")
    text = call_gemini(build_prompt(topic, number, difficulty), api_key, model, timeout)
    return {"topic": topic, "difficulty": difficulty,
            "questions": validate_questions(_extract_json(text), number)}
