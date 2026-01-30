import os
from groq import Groq
import config
import utils

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
           - If "pjrofessional": Be insightful, polite, and clear.
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
        import re
        reply = re.sub(r'<[^>]+>', '', reply)  # Remove HTML tags
        reply = re.sub(r'\*\*.*?\*\*', '', reply)  # Remove markdown bold
        reply = re.sub(r'\*.*?\*', '', reply)  # Remove markdown italic
        
        return reply
    except Exception as e:
        return f"Error generating reply: {e}"