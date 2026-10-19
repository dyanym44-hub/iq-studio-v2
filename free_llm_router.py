"""
موجّه نماذج مجانية: يجرّب المزوّدين بالترتيب وينتقل للتالي عند انتهاء الحد المجاني.

التثبيت:   pip install openai
التشغيل:   اضبط مفاتيح API كمتغيرات بيئة (تكفي مفاتيح بعض المزوّدين فقط) ثم:
           python free_llm_router.py
"""
import os
import time
from openai import OpenAI

# الترتيب = الأولوية. عدّل النماذج حسب القائمة لأنها تتغير باستمرار.
PROVIDERS = [
    {"name": "Groq", "base_url": "https://api.groq.com/openai/v1",
     "key_env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b"},
    {"name": "Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
     "key_env": "GEMINI_API_KEY", "model": "gemini-2.5-flash"},
    {"name": "Mistral", "base_url": "https://api.mistral.ai/v1",
     "key_env": "MISTRAL_API_KEY", "model": "mistral-small-latest"},
    {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "key_env": "OPENROUTER_API_KEY", "model": "openrouter/free"},
    {"name": "NVIDIA", "base_url": "https://integrate.api.nvidia.com/v1",
     "key_env": "NVIDIA_API_KEY", "model": "nvidia/nemotron-3-super-120b-a12b"},
]

COOLDOWN_SECONDS = 300  # مدة إيقاف المزوّد بعد فشله
_blocked_until = {}


def chat(messages, timeout=60):
    """يرسل المحادثة لأول مزوّد متاح ويرجع (النص، اسم المزوّد)."""
    errors = []
    for p in PROVIDERS:
        key = os.getenv(p["key_env"])
        if not key:
            continue
        if _blocked_until.get(p["name"], 0) > time.time():
            continue
        try:
            client = OpenAI(base_url=p["base_url"], api_key=key, timeout=timeout)
            r = client.chat.completions.create(model=p["model"], messages=messages)
            return r.choices[0].message.content, p["name"]
        except Exception as e:  # حد الاستخدام، خادم، شبكة...
            _blocked_until[p["name"]] = time.time() + COOLDOWN_SECONDS
            errors.append(f"{p['name']}: {type(e).__name__}")
    raise RuntimeError("فشل كل المزوّدين: " + " | ".join(errors or ["لا توجد مفاتيح مضبوطة"]))


if __name__ == "__main__":
    history = []
    print("اكتب رسالتك (exit للخروج)")
    while True:
        text = input("\nأنت: ").strip()
        if text.lower() in ("exit", "quit"):
            break
        history.append({"role": "user", "content": text})
        reply, provider = chat(history)
        history.append({"role": "assistant", "content": reply})
        print(f"\n[{provider}] {reply}")
