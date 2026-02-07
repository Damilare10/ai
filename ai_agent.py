import os
from groq import Groq
import config
import utils
import json
import re

def generate_reply(tweet_text, tone="professional", user_id=None):
    """
    Generates a reply to a tweet using Groq (llama-3.1-8b-instant).
    """
    try:
        # Fetch API key from config (Shared Key)
        api_key = config.GROQ_API_KEY
        
        if not api_key:
            return "Error: System GROQ API key not configured. Please check .env file."
            
        client = Groq(api_key=api_key)
        
        prompt = f"""
        You are a Twitter user replying to a tweet. Your goal is to be engaging, relevant, and sound like a real person, not a bot.

        Tweet: "{tweet_text}"

        Instructions:
        1. **Persona:** Adopt a {tone} tone.
           - If "casual": Be chill, use lowercase if it fits, maybe slang like "tbh" or "ngl" if appropriate.
           - If "professional": Be insightful, polite, and clear.
           - If "funny": Make a light joke or witty observation.
        2. **Substance:** Do NOT just say "Great project" or "Sounds good". 
           - Pick one specific detail from the tweet to comment on.
           - Share a quick related opinion.
        3. **Length:** Keep it under 200 characters. Short and punchy.
        4. **CRITICAL - NO HTML/MARKUP:** Do NOT use ANY HTML tags like <div>, <p>, <span>, etc. Do NOT use markdown formatting.
        5. **Formatting:** ABSOLUTELY NO hashtags. NO bold, NO italics, NO asterisks (*).
        6. **Strict Constraints:** Do NOT use double quotes (") or single quotes ('). Just plain text.
        7. **Emoji:** Use 0-1 emojis max where appropriate. Don't overdo it.
        
        OUTPUT ONLY THE REPLY TEXT - NO LABELS, NO FORMATTING, NO HTML TAGS.

        Reply:
        """
        
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=1,
            max_completion_tokens=1024,
            top_p=1,
            stream=False,
            stop=None,
        )

        reply = completion.choices[0].message.content.strip()
        
        # Safety: Strip any HTML tags if the AI ignores instructions
        reply = re.sub(r'<[^>]+>', '', reply)  # Remove HTML tags
        reply = re.sub(r'\*\*.*?\*\*', '', reply)  # Remove markdown bold
        reply = re.sub(r'\*.*?\*', '', reply)  # Remove markdown italic
        
        return reply
    except Exception as e:
        return f"Error generating reply: {e}"

def generate_batch_replies(tweets_data: list[dict], tone="professional", user_id=None) -> list[dict]:
    """
    Generates replies for a batch of tweets (up to 5).
    Input: [{'id': '123', 'text': 'Hello'}, ...]
    Output: [{'id': '123', 'reply': 'Hi there'}]
    """
    try:
        api_key = config.GROQ_API_KEY
        if not api_key:
            return [{"id": t['id'], "reply": "Error: Groq Key Missing"} for t in tweets_data]
            
        client = Groq(api_key=api_key)
        
        # Construct Batch Prompt
        tweets_json_str = json.dumps(tweets_data, indent=2)
        
        prompt = f"""
        You are a Twitter user replying to {len(tweets_data)} different tweets.
        Your goal is to be engaging, relevant, and sound like a real person.

        **INPUT TWEETS (JSON):**
        {tweets_json_str}

        **INSTRUCTIONS:**
        1. **Persona:** Adopt a {tone} tone.
        2. **Output Format:** Return a STRICT JSON ARRAY of objects. Each object must have "id" (matching input) and "reply".
           Example: [ {{"id": "123", "reply": "Cool stuff!"}}, {{"id": "456", "reply": "Nice one!"}} ]
        3. **Content:** Pick a specific detail to comment on. No generic "Nice tweet".
        4. **Length:** Under 200 chars per reply.
        5. **No Formatting:** Plain text only. No hashtags, no markdown.
        6. **CRITICAL:** Ensure valid JSON - proper commas between objects, no trailing commas.

        **OUTPUT ONLY THE JSON ARRAY. NO MARKDOWN BLOCK. NO EXTRA TEXT.**
        """

        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8 if attempt == 0 else 0.5,  # Lower temp on retry
                    max_completion_tokens=1500,
                    top_p=1,
                    stream=False,
                    stop=None,
                )

                response_text = completion.choices[0].message.content.strip()
                
                # Clean potential markdown wrapping ```json ... ```
                if response_text.startswith("```"):
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                    response_text = response_text.strip()
                
                # Try to extract JSON array using regex (more robust)
                json_match = re.search(r'\[[\s\S]*\]', response_text)
                if json_match:
                    response_text = json_match.group(0)
                
                # Attempt to fix common JSON issues
                # Remove trailing commas before ] or }
                response_text = re.sub(r',\s*]', ']', response_text)
                response_text = re.sub(r',\s*}', '}', response_text)
                
                replies_data = json.loads(response_text)
                
                # Validate structure
                if not isinstance(replies_data, list):
                    raise ValueError("Response is not a list")
                
                # Sanitize replies
                for item in replies_data:
                    r = item.get("reply", "")
                    r = re.sub(r'<[^>]+>', '', r)
                    r = re.sub(r'\*\*.*?\*\*', '', r)
                    item["reply"] = r
                    
                return replies_data
                
            except json.JSONDecodeError as e:
                last_error = e
                print(f"Batch JSON parse error (attempt {attempt + 1}): {e}")
                continue  # Retry
            except Exception as e:
                last_error = e
                print(f"Batch generation error (attempt {attempt + 1}): {e}")
                continue  # Retry
        
        # All retries failed - fallback to individual generation
        print(f"Batch generation failed after {max_retries} attempts. Falling back to individual generation...")
        results = []
        for tweet in tweets_data:
            reply = generate_reply(tweet['text'], tone, user_id)
            results.append({"id": tweet['id'], "reply": reply})
        return results

    except Exception as e:
        print(f"Batch generation critical error: {e}")
        # Fallback: Error for all
        return [{"id": t['id'], "reply": f"Error: {str(e)[:50]}"} for t in tweets_data]