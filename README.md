# Intelligence-Mental-Health-Chatbot

## Manual Setup
Download python version 3.11.0
```
curl -o python-3.11.0.exe https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe
```

Install python version 3.11.0
```
./python-3.11.0.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
```

Create virtual environment
```
python -m venv venv
```

Activate virtual environment (Windows)
```
venv\Scripts\activate
```

Install requirements dependencies
```
pip install -r requirements.txt
```

Run app.py
```
python app.py
```

## Auto Setup
```
./run.bat
```