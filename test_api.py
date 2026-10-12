import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
key = os.getenv('ANTHROPIC_API_KEY')
print(f'API Key loaded: {bool(key)}')
if key:
    print(f'Key starts with: {key[:20]}...')

try:
    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model='claude-opus-4',
        max_tokens=10,
        messages=[{'role': 'user', 'content': 'hi'}]
    )
    print('OK - API works!')
except Exception as e:
    print(f'ERROR: {e}')
