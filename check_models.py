import os
from dotenv import load_dotenv
import httpx

load_dotenv()
key = os.getenv('ANTHROPIC_API_KEY')

headers = {
    'x-api-key': key,
    'anthropic-version': '2023-06-01'
}

try:
    response = httpx.get(
        'https://api.anthropic.com/v1/models',
        headers=headers,
        timeout=10
    )
    if response.status_code == 200:
        import json
        data = response.json()
        print('Available models:')
        for model in data.get('data', []):
            print(f'  - {model.get("id")}')
    else:
        print(f'Error: {response.status_code}')
        print(response.text)
except Exception as e:
    print(f'Error: {e}')