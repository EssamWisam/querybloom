
import os
from litellm import completion

# Set the key provided by the user
os.environ["GEMINI_API_KEY"] = "AIzaSyCqE8d8yk7wNn_WkwZR1ZBowxMU8osqyZo"

try:
    response = completion(
        model="gemini/gemini-1.5-flash",
        messages=[{"role": "user", "content": "Hello, are you working?"}]
    )
    print("Success:")
    print(response.choices[0].message.content)
except Exception as e:
    print(f"Error: {e}")
