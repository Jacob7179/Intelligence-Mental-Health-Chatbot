# Intelligence-Mental-Health-Chatbot

## Auto Setup
```
./run.bat
```

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

> [!TIP]\
> Create **.env** file if not available.
>
> Content:
>
> MONGODB_URI=mongodb://localhost:27017/
>
> MONGODB_DB=mental_health_chatbot
>
> SECRET_KEY=your-secret-key-here-change-in-production
>
> GEMINI_API_KEY=<Your_Gemini_API_Keys>
>
> DEFAULT_API=gemini