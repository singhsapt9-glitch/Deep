BANK GUARD AI — ਸੁਧਾਰਿਆ ਹੋਇਆ ਪ੍ਰੋਟੋਟਾਈਪ

ਫਾਈਲਾਂ:
- bank_guard_ai_hardened.py : ਸੁਧਾਰਿਆ ਹੋਇਆ ਮੁੱਖ ਕੋਡ
- requirements_bank_guard.txt : Python packages

ਚਲਾਉਣ ਦੇ ਕਦਮ:
1. Python 3.10 ਜਾਂ ਨਵਾਂ ਵਰਜਨ ਵਰਤੋ।
2. Terminal ਵਿੱਚ ਚਲਾਓ:
   pip install -r requirements_bank_guard.txt
3. Hugging Face AI ਚੋਣ ਵਿਕਲਪਿਕ ਹੈ। ਇਸ ਲਈ HF_TOKEN environment secret ਵਜੋਂ ਸੈੱਟ ਕਰੋ।
   Token ਨੂੰ Python ਫਾਈਲ ਵਿੱਚ hard-code ਨਾ ਕਰੋ।
4. Offline Punjabi voice ਲਈ operating system ਵਿੱਚ espeak-ng install ਹੋਣਾ ਚਾਹੀਦਾ ਹੈ।
   eSpeak-NG ਨਾ ਹੋਵੇ ਤਾਂ ਬਾਕੀ app ਚੱਲੇਗੀ, ਪਰ audio ਨਹੀਂ ਬਣੇਗੀ।
5. ਚਲਾਓ:
   python bank_guard_ai_hardened.py
6. Default ਤੌਰ 'ਤੇ app ਸਿਰਫ਼ ਆਪਣੇ computer ਦੇ localhost 'ਤੇ ਖੁੱਲ੍ਹਦੀ ਹੈ।

Privacy ਵਿੱਚ ਕੀ ਬਦਲਿਆ:
- Raw transaction descriptions, dates, account identifiers ਅਤੇ amounts Hugging Face ਨੂੰ ਨਹੀਂ ਭੇਜੇ ਜਾਂਦੇ।
- External AI checkbox default OFF ਹੈ। ON ਕਰਨ 'ਤੇ ਸਿਰਫ਼ fixed category names ਅਤੇ counts ਭੇਜੇ ਜਾਂਦੇ ਹਨ।
- Dates, amounts ਅਤੇ raw descriptions AI prompt ਵਿੱਚ ਸ਼ਾਮਲ ਨਹੀਂ ਹਨ।
- Upload ਨੂੰ binary bytes ਵਜੋਂ process ਕੀਤਾ ਜਾਂਦਾ ਹੈ; callback user-supplied filesystem path ਨਹੀਂ ਲੈਂਦਾ।
- Gradio upload/output cache ਲਈ scheduled cleanup ਚਾਲੂ ਹੈ।
- User-facing report ਵਿੱਚ raw transaction description ਨਹੀਂ ਦਿਖਾਈ ਜਾਂਦੀ।
- eSpeak-NG ਨੂੰ shell=False ਅਤੇ timeout ਨਾਲ ਚਲਾਇਆ ਜਾਂਦਾ ਹੈ; text stdin ਰਾਹੀਂ ਜਾਂਦਾ ਹੈ।
- Negative amounts ਨੂੰ parser ਵਿੱਚ ਕਾਇਮ ਰੱਖਿਆ ਗਿਆ ਹੈ।

ਬਹੁਤ ਜ਼ਰੂਰੀ ਸੀਮਾਵਾਂ:
- ਇਹ code zero-trace ਦੀ guarantee ਨਹੀਂ ਦਿੰਦਾ। Python RAM ਨੂੰ ਪੱਕੇ ਤੌਰ 'ਤੇ wipe ਨਹੀਂ ਕਰ ਸਕਦਾ;
  OS swap, filesystem snapshots, crash dumps ਅਤੇ platform-level logs ਵੀ ਹੋ ਸਕਦੇ ਹਨ।
- Gradio ਦਾ delete_cache periodic ਹੈ; ਇਸ ਦਾ ਮਤਲਬ ਹਰ file ਤੁਰੰਤ ਮਿਟਣਾ ਨਹੀਂ।
- PDF parsing ਅਜੇ ਵੀ ਇਸੇ process ਵਿੱਚ ਹੈ। Public production ਲਈ ਵੱਖਰੇ resource-limited worker/container
  ਵਿੱਚ CPU, RAM ਅਤੇ wall-clock limits ਨਾਲ PDF parsing ਕਰਵਾਓ।
- Rate limiter in-memory ਅਤੇ single-process ਹੈ। Multi-worker deployment ਲਈ Redis-backed limiter
  ਅਤੇ authenticated user identity ਲੋੜੀਂਦੀ ਹੈ।
- Public bind ਲਈ BG_USERNAME ਅਤੇ BG_PASSWORD ਲਾਜ਼ਮੀ ਹਨ। Better option: trusted identity-aware
  reverse proxy ਅਤੇ HTTPS.
- Hugging Face provider retention/privacy terms ਨੂੰ ਆਪਣੇ deployment ਤੋਂ ਪਹਿਲਾਂ verify ਕਰੋ।
- Category keyword matching false positives ਅਤੇ false negatives ਦੇ ਸਕਦੀ ਹੈ। ਇਹ fraud detector
  ਜਾਂ RBI/legal advice ਨਹੀਂ ਹੈ।
- ਪਹਿਲਾਂ synthetic/sample statements ਨਾਲ test ਕਰੋ; ਅਸਲੀ statements ਨੂੰ public demo ਵਿੱਚ ਨਾ ਪਾਓ।
