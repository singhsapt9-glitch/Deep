import random

# ਕੰਪਿਊਟਰ 1 ਤੋਂ 10 ਤੱਕ ਕੋਈ ਲੁਕਵਾਂ ਨੰਬਰ ਆਪਣੇ ਆਪ ਚੁਣ ਲਵੇਗਾ
target = random.randint(1, 10)

# ਗਿਣਤੀ ਕਰਨ ਲਈ ਕਿ ਕਿੰਨੀ ਵਾਰ ਕੋਸ਼ਿਸ਼ ਕੀਤੀ ਹੈ
count = 0

# while True ਦਾ ਮਤਲਬ ਹੈ ਕਿ ਜਦੋਂ ਤੱਕ ਸਹੀ ਨੰਬਰ ਨਹੀਂ ਮਿਲਦਾ, ਲੂਪ ਚਲਦਾ ਰਹੇਗਾ
while True:
    count = count + 1
    user_choice = int(input("Enter your number: "))
    
    # ਜੇ ਯੂਜ਼ਰ ਦਾ ਨੰਬਰ ਅਤੇ ਕੰਪਿਊਟਰ ਦਾ ਨੰਬਰ ਇੱਕੋ ਜਿਹੇ ਹੋ ਗਏ, ਤਾਂ ਗੇਮ ਜਿੱਤ ਗਏ
    if user_choice == target:
        print("buet bidea tusi number lab gy")
        break
        
    # ਜੇ ਯੂਜ਼ਰ ਦਾ ਨੰਬਰ ਛੋਟਾ ਹੈ ਤਾਂ ਸੁਨੇਹਾ ਦੇਵੋ
    elif user_choice < target:
        print("tuda numer bhot shota hi")
        
    # ਜੇ ਵੱਡਾ ਹੈ ਤਾਂ ਇਹ ਚੱਲੇਗਾ
    else:
        print("tudya nimber but bada hi")
