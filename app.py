import streamlit as st
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from google import genai

# 1. ਵੈੱਬਸਾਈਟ ਦੀ ਸੈਟਿੰਗ ਅਤੇ ਸਿਰਲੇਖ
st.set_page_config(page_title="AI ਖੇਤੀਬਾੜੀ ਸਲਾਹਕਾਰ", page_icon="🌾", layout="centered")
st.title("🌾 ਸਮਾਰਟ AI ਖੇਤੀਬਾੜੀ ਸਲਾਹਕਾਰ")
st.write("ਆਪਣੇ ਖੇਤ ਦੀ ਮਿੱਟੀ ਅਤੇ ਮੌਸਮ ਦੇ ਅੰਕੜੇ ਭਰੋ, ਅਤੇ AI ਤੋਂ ਸਹੀ ਫ਼ਸਲ ਤੇ ਖਾਦ ਦੀ ਪੂਰੀ ਸਲਾਹ ਲਓ।")

# 2. ਸਾਈਡਬਾਰ ਵਿੱਚ API Key ਲੈਣਾ (ਸੁਰੱਖਿਆ ਲਈ)
st.sidebar.header("🔑 AI ਸੈਟਿੰਗ")
api_key = st.sidebar.text_input("ਆਪਣੀ Google Gemini API Key ਇੱਥੇ ਪਾਓ:", type="password")
st.sidebar.info("ਇਹ ਪ੍ਰੋਜੈਕਟ Machine Learning (Random Forest) ਅਤੇ Agentic AI ਦੀ ਮਦਦ ਨਾਲ ਤਿਆਰ ਕੀਤਾ ਗਿਆ ਹੈ।")

# 3. ਡਾਟਾ ਲੋਡ ਕਰਨਾ ਅਤੇ ਮਾਡਲ ਟ੍ਰੇਨ ਕਰਨਾ
@st.cache_resource
def load_and_train():
    df = pd.read_csv('Crop_recommendation.csv')
    X = df.drop(columns=['label'])
    y = df['label']
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)
    return model

model = load_and_train()

# 4. ਕਿਸਾਨ ਤੋਂ ਮਿੱਟੀ ਦੇ ਅੰਕੜੇ ਲੈਣ ਲਈ ਡੱਬੇ
st.subheader("📊 ਖੇਤ ਦੀ ਮਿੱਟੀ ਅਤੇ ਮੌਸਮ ਦੇ ਅੰਕੜੇ ਭਰੋ:")
col1, col2 = st.columns(2)

with col1:
    N = st.number_input("ਨਾਈਟ੍ਰੋਜਨ - Nitrogen (N)", min_value=0, max_value=200, value=90)
    P = st.number_input("ਫਾਸਫੋਰਸ - Phosphorus (P)", min_value=0, max_value=200, value=42)
    K = st.number_input("ਪੋਟਾਸ਼ੀਅਮ - Potassium (K)", min_value=0, max_value=250, value=43)
    ph = st.number_input("ਮਿੱਟੀ ਦਾ ਖਾਰਾਪਣ (Soil pH)", min_value=0.0, max_value=14.0, value=6.5)

with col2:
    temp = st.number_input("ਤਾਪਮਾਨ - Temperature (°C)", min_value=0.0, max_value=50.0, value=20.8)
    humidity = st.number_input("ਨਮੀ - Humidity (%)", min_value=0.0, max_value=100.0, value=82.0)
    rainfall = st.number_input("ਬਾਰਿਸ਼ - Rainfall (mm)", min_value=0.0, max_value=400.0, value=202.9)

# 5. ਬਟਨ ਦਬਾਉਣ 'ਤੇ ਨਤੀਜਾ ਅਤੇ AI ਸਲਾਹ ਦਿਖਾਉਣਾ
if st.button("🌱 ਫ਼ਸਲ ਅਤੇ AI ਸਲਾਹ ਪਤਾ ਕਰੋ", type="primary"):
    khet_data = [[N, P, K, temp, humidity, ph, rainfall]]
    chuni_fasal = model.predict(khet_data)[0]
    
    st.success(f"### ✅ ਸਾਡੇ ML ਮਾਡਲ ਅਨੁਸਾਰ ਸਭ ਤੋਂ ਵਧੀਆ ਫ਼ਸਲ: **{chuni_fasal.upper()}**")
    
    if api_key:
        with st.spinner("⏳ AI ਖੇਤੀਬਾੜੀ ਮਾਹਿਰ ਕਿਸਾਨ ਲਈ ਰਿਪੋਰਟ ਤਿਆਰ ਕਰ ਰਿਹਾ ਹੈ..."):
            try:
                client = genai.Client(api_key=api_key)
                prompt = f"""
                ਤੁਸੀਂ ਪੰਜਾਬ ਦੇ ਇੱਕ ਤਜਰਬੇਕਾਰ ਖੇਤੀਬਾੜੀ ਮਾਹਿਰ (AI Agriculture Agent) ਹੋ।
                ਇੱਕ ਕਿਸਾਨ ਦੇ ਖੇਤ ਦੀ ਮਿੱਟੀ ਦੀ ਜਾਂਚ ਦੇ ਅੰਕੜੇ ਹੇਠ ਲਿਖੇ ਅਨੁਸਾਰ ਹਨ:
                - ਨਾਈਟ੍ਰੋਜਨ (N): {N}, ਫਾਸਫੋਰਸ (P): {P}, ਪੋਟਾਸ਼ੀਅਮ (K): {K}
                - ਤਾਪਮਾਨ: {temp}°C, ਨਮੀ: {humidity}%, ਮਿੱਟੀ ਦਾ pH: {ph}, ਬਾਰਿਸ਼: {rainfall} mm

                ਸਾਡੇ Machine Learning ਮਾਡਲ ਨੇ ਇਸ ਖੇਤ ਲਈ '{chuni_fasal}' (ਫ਼ਸਲ) ਦੀ ਸਿਫ਼ਾਰਸ਼ ਕੀਤੀ ਹੈ।
                ਕਿਰਪਾ ਕਰਕੇ ਕਿਸਾਨ ਨੂੰ ਸੌਖੀ ਅਤੇ ਸਾਫ਼ ਪੰਜਾਬੀ ਵਿੱਚ ਹੇਠ ਲਿਖੇ 3 ਨੁਕਤਿਆਂ ਵਿੱਚ ਸਲਾਹ ਦਿਓ:
                1. ਇਹ ਫ਼ਸਲ ਇਸ ਮਿੱਟੀ ਲਈ ਕਿਉਂ ਸਹੀ ਹੈ?
                2. ਮਿੱਟੀ ਦੇ ਮੌਜੂਦਾ ਤੱਤਾਂ (N, P, K) ਮੁਤਾਬਕ ਕਿਹੜੀ ਖਾਦ (ਯੂਰੀਆ, DAP, ਪੋਟਾਸ਼) ਕਿੰਨੀ ਵਰਤਣੀ ਚਾਹੀਦੀ ਹੈ?
                3. ਸਿੰਚਾਈ ਅਤੇ ਬਿਮਾਰੀਆਂ ਤੋਂ ਬਚਾਅ ਲਈ 2 ਜ਼ਰੂਰੀ ਸੁਝਾਅ।
                """
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                )
                st.markdown("---")
                st.markdown(response.text)
            except Exception as e:
                st.error(f"AI ਨਾਲ ਜੁੜਨ ਵਿੱਚ ਦਿੱਕਤ ਆਈ: {e}")
    else:
        st.warning("⚠️ ਪੰਜਾਬੀ ਵਿੱਚ ਖਾਦ ਅਤੇ ਸਿੰਚਾਈ ਦੀ ਪੂਰੀ AI ਸਲਾਹ ਲੈਣ ਲਈ ਖੱਬੇ ਪਾਸੇ ਸਾਈਡਬਾਰ ਵਿੱਚ ਆਪਣੀ Google Gemini API Key ਪਾਓ।")
