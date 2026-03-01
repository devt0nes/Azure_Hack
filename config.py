# config.py
from openai import AsyncAzureOpenAI
from azure.cosmos import CosmosClient
from dotenv import load_dotenv
import os

load_dotenv()

openai_client = AsyncAzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

cosmos_client = CosmosClient(
    os.getenv("COSMOS_ENDPOINT"), credential=os.getenv("COSMOS_KEY")
)
cosmos_db = cosmos_client.get_database_client(os.getenv("COSMOS_DB_NAME"))

SB_CONN  = os.getenv("SERVICE_BUS_CONN_STR")
SB_QUEUE = os.getenv("SERVICE_BUS_QUEUE")

GPT4O = os.getenv("OPENAI_GPT4O_DEPLOYMENT")
MINI  = os.getenv("OPENAI_MINI_DEPLOYMENT")
O1    = os.getenv("OPENAI_O1_DEPLOYMENT")