import os
import base64
import httpx
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# BLOB STORAGE CLIENT
# ─────────────────────────────────────────────

blob_service_client = BlobServiceClient.from_connection_string(
    os.getenv("BLOB_STORAGE_CONNECTION_STRING")
)

def upload_file(container_name: str, blob_name: str, file_path: str) -> str:
    """Upload a local file to blob storage. Returns the blob URL."""
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
    with open(file_path, "rb") as f:
        blob_client.upload_blob(f, overwrite=True)
    return blob_client.url

def download_file(container_name: str, blob_name: str, download_path: str) -> str:
    """Download a blob to a local file. Returns the local path."""
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
    with open(download_path, "wb") as f:
        f.write(blob_client.download_blob().readall())
    return download_path

def list_files(container_name: str) -> list[str]:
    """List all blob names in a container."""
    container_client = blob_service_client.get_container_client(container_name)
    return [blob.name for blob in container_client.list_blobs()]

def download_blob_bytes(blob_url: str) -> bytes:
    """Download a blob from its URL and return raw bytes."""
    with httpx.Client() as client:
        response = client.get(blob_url)
        response.raise_for_status()
        return response.content

# ─────────────────────────────────────────────
# AZURE OPENAI CLIENT
# ─────────────────────────────────────────────

openai_client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-01"
)

GPT4O = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT4O", "gpt-4o")
GPT4O_MINI = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT4O_MINI", "gpt-4o-mini")

def call_gpt4o(prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
    """Call GPT-4o with a text prompt."""
    response = openai_client.chat.completions.create(
        model=GPT4O,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2000
    )
    return response.choices[0].message.content

def call_gpt4o_mini(prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
    """Call GPT-4o-mini with a text prompt."""
    response = openai_client.chat.completions.create(
        model=GPT4O_MINI,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2000
    )
    return response.choices[0].message.content

def call_gpt4o_vision(image_bytes: bytes, prompt: str) -> str:
    """Call GPT-4o with an image and a text prompt."""
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    response = openai_client.chat.completions.create(
        model=GPT4O,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        max_tokens=2000
    )
    return response.choices[0].message.content