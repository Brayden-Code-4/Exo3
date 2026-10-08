import os

from dotenv import load_dotenv

load_dotenv()

# Server-side settings only: none of these values is ever sent to the browser except the model list.
RODIUMAI_BASE_URL = os.getenv("RODIUMAI_BASE_URL", "https://api.rodiumai.io/v1").rstrip("/")
RODIUMAI_API_KEY = os.environ["RODIUMAI_API_KEY"]

# Models the user may pick, as "id" or "id=Label", comma separated. The client choice is always checked
# against this list: anything else is rejected with a 400.
DEFAULT_ALLOWED_MODELS = (
    "anthropic/claude-sonnet-4-5-20250929=Claude Sonnet 4.5,"
    "anthropic/claude-haiku-4-5-20251001=Claude Haiku 4.5,"
    "openai/gpt-4o-mini=GPT-4o mini"
)


def parse_models(raw: str) -> dict[str, str]:
    models: dict[str, str] = {}
    for item in raw.split(","):
        model_id, _, label = item.strip().partition("=")
        model_id = model_id.strip()
        if model_id:
            models[model_id] = label.strip() or model_id
    return models


ALLOWED_MODELS = parse_models(os.getenv("RODIUMAI_MODELS", DEFAULT_ALLOWED_MODELS))
if not ALLOWED_MODELS:
    raise RuntimeError("RODIUMAI_MODELS must contain at least one model.")

# The default model must itself be allowed; fall back to the first one of the list otherwise.
DEFAULT_MODEL = os.getenv("RODIUMAI_MODEL", "")
if DEFAULT_MODEL not in ALLOWED_MODELS:
    DEFAULT_MODEL = next(iter(ALLOWED_MODELS))

MAX_TOKENS = int(os.getenv("RODIUMAI_MAX_TOKENS", "1024"))
