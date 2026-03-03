import os
import json
from cryptography.fernet import Fernet

class SecretsManager:
    """
    Class to handle secrets management securely.
    Uses encryption to store and retrieve sensitive data.
    """
    def __init__(self, secrets_file="secrets.json", key_file="secret.key"):
        self.secrets_file = secrets_file
        self.key_file = key_file
        self.key = self._load_or_generate_key()

    def _load_or_generate_key(self):
        """
        Load the encryption key from file or generate a new one.
        """
        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as key_file:
                return key_file.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_file, "wb") as key_file:
                key_file.write(key)
            return key

    def store_secret(self, key, value):
        """
        Encrypt and store a secret in the secrets file.
        """
        fernet = Fernet(self.key)
        encrypted_value = fernet.encrypt(value.encode())
        
        secrets = self._load_secrets()
        secrets[key] = encrypted_value.decode()

        with open(self.secrets_file, "w") as file:
            json.dump(secrets, file)

    def get_secret(self, key):
        """
        Retrieve and decrypt a secret from the secrets file.
        """
        fernet = Fernet(self.key)
        secrets = self._load_secrets()

        if key in secrets:
            encrypted_value = secrets[key]
            return fernet.decrypt(encrypted_value.encode()).decode()
        else:
            raise KeyError(f"Secret '{key}' not found.")

    def _load_secrets(self):
        """
        Load secrets from the secrets file.
        """
        if os.path.exists(self.secrets_file):
            with open(self.secrets_file, "r") as file:
                return json.load(file)
        return {}

# Example usage
if __name__ == "__main__":
    secrets_manager = SecretsManager()
    secrets_manager.store_secret("db_password", "super_secure_password")
    print(f"Retrieved secret: {secrets_manager.get_secret('db_password')}")