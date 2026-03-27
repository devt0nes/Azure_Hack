# Agentic Nexus

### Run Without Venv (Windows)

Backend setup and run:
```powershell
cd platform-backend
python -m pip install --upgrade pip
python -m pip install -r requirements-runtime.txt
python backend_platform.py
```

Frontend setup and run:
```powershell
cd platform-frontend
npm install
npm run dev
```

If port 8000 is already in use, stop old backend processes and restart.

### Run Without Venv (macOS/Linux)

Backend:
```bash
cd platform-backend
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-runtime.txt
python3 backend_platform.py
```

Frontend:
```bash
cd platform-frontend
npm install
npm run dev
```