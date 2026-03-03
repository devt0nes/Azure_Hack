# Security Audit Tool

## Overview
The Security Audit Tool is designed to assist in performing basic security tasks such as encryption, compliance checks, and threat simulations. It supports best practices in security engineering and aids in ensuring compliance with regulations like GDPR, HIPAA, and SOC2.

## Features
- **File Encryption**: Encrypts files using AES-256 encryption.
- **Compliance Checks**: Dummy compliance checker for GDPR, HIPAA, and SOC2.
- **Threat Simulation**: Simulates security threats to test system response.

## Requirements
- Python 3.8+
- `cryptography` library

## Setup
1. Install dependencies:
   ```bash
   pip install cryptography
   ```
2. Set the environment variable for the encryption key (optional):
   ```bash
   export ENCRYPTION_KEY=<your-encryption-key>
   ```

## Usage
1. Run the tool:
   ```bash
   python security_audit_tool.py
   ```
2. Review the logs in `security_audit.log`.

## Logging
All actions are logged in `security_audit.log` for auditing and debugging purposes.

## Notes
- This tool is a basic implementation and may require customization for production use.
- Ensure the encryption key is securely stored and rotated periodically.