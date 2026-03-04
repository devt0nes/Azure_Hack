import os
from azure.storage.blob import BlobServiceClient, BlobServiceProperties, RetentionPolicy
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# BLOB STORAGE SETUP
# ─────────────────────────────────────────────

def setup_blob_storage():
    connection_string = os.getenv("BLOB_STORAGE_CONNECTION_STRING")
    client = BlobServiceClient.from_connection_string(connection_string)

    # Create containers if they don't exist
    containers = ["raw-uploads", "processed-schemas"]
    for container_name in containers:
        try:
            client.create_container(container_name)
            print(f"✅ Created container: {container_name}")
        except Exception as e:
            if "ContainerAlreadyExists" in str(e):
                print(f"ℹ️  Container already exists: {container_name}")
            else:
                raise e

    # Set 30-day auto-delete lifecycle on raw-uploads
    try:
        props = client.get_service_properties()
        props["delete_retention_policy"] = RetentionPolicy(enabled=True, days=30)
        client.set_service_properties(
            delete_retention_policy=RetentionPolicy(enabled=True, days=30)
        )
        print("✅ Set 30-day retention policy on raw-uploads")
    except Exception as e:
        print(f"⚠️  Could not set retention policy: {e}")

    print("\n✅ Blob Storage setup complete.")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Setting up infrastructure...\n")
    setup_blob_storage()
    print("\n🎉 All setup complete!")