import os
from dotenv import load_dotenv
from azure.ai.contentsafety import ContentSafetyClient
from azure.ai.contentsafety.models import AnalyzeTextOptions
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.ai.contentsafety.models import AnalyzeTextOptions, TextCategory

load_dotenv()

endpoint = os.environ.get("CONTENT_SAFETY_ENDPOINT", "")
key = os.environ.get("CONTENT_SAFETY_KEY", "")

client = None
if endpoint and key:
    try:
        client = ContentSafetyClient(endpoint, AzureKeyCredential(key))
        print(f"✅ Content Safety client initialized: {endpoint}")
    except Exception as e:
        print(f"❌ Content Safety client failed: {e}")
else:
    print("⚠️ Content Safety not configured — running without safety checks")


def analyze_text(text: str) -> dict:
    if not client:
        return {"is_safe": True, "blocked_reason": None, "scores": {}}

    try:
        request = AnalyzeTextOptions(
            text=text[:1000],
            categories=[
                TextCategory.HATE,
                TextCategory.SELF_HARM,
                TextCategory.SEXUAL,
                TextCategory.VIOLENCE,
    ]
)
        response = client.analyze_text(request)

        scores = {}
        for item in response.categories_analysis:
            scores[str(item.category)] = item.severity

        print(f"Content Safety scores: {scores}")

        # Block if any category scores 2 or higher
        max_score = max(scores.values()) if scores else 0
        is_safe = max_score < 2

        blocked_reason = None
        if not is_safe:
            worst_category = max(scores, key=scores.get)
            blocked_reason = f"Content flagged for: {worst_category} (severity: {scores[worst_category]})"

        return {
            "is_safe": is_safe,
            "blocked_reason": blocked_reason,
            "scores": scores
        }

    except HttpResponseError as e:
        print(f"Content Safety API error: {e}")
        return {"is_safe": True, "blocked_reason": None, "scores": {}}
    except Exception as e:
        print(f"Content Safety unexpected error: {e}")
        return {"is_safe": True, "blocked_reason": None, "scores": {}}


def check_input(user_input: str) -> dict:
    return analyze_text(user_input)


def check_output(generated_code: str) -> dict:
    return analyze_text(generated_code)