import asyncio
import os
import base64
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
import uvicorn
import google.generativeai as genai
import edge_tts

# --- Gemini API の初期設定 ---
# 💡 ご提示いただいた通り、確実な動作のために2.5-flashへアップデート
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# クラウドTTS (edge-tts) の音声合成関数
async def generate_cloud_audio(text: str, voice: str, rate: str, pitch: str) -> bytes:
    try:
        # フロントから届いた rate("+15%") や pitch("+0Hz") をそのまま適用
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data
    except Exception as e:
        print(f"クラウド音声合成エラー: {e}")
        return b""

app = FastAPI()
app.mount("/static", StaticFiles(directory="."), name="static")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("【サーバー側】ブラウザと接続されました。")
    
    chat = model.start_chat(history=[
        {
            "role": "user", 
            "parts": "あなたは等身大ディスプレイの中にいるサイバーアシスタントです。フランクかつ親しみやすい口調で、2〜3文の短めの文章で回答してください。"
        },
        {
            "role": "model", 
            "parts": "了解！設定に合わせた最適なボイスでサポートするよ！"
        }
    ])
    
    current_voice = "ja-JP-NanamiNeural"
    current_rate = "+15%"
    current_pitch = "+0Hz"
    
    try:
        while True:
            data = await websocket.receive_json()
            
            # ① 設定更新リクエストの場合
            if data.get("type") == "settings":
                current_voice = data.get("voice", current_voice)
                current_rate = data.get("rate", current_rate)
                current_pitch = data.get("pitch", current_pitch)
                print(f"【設定更新】voice: {current_voice}, rate: {current_rate}, pitch: {current_pitch}")
                continue
                
            # ② 通常のテキスト対話リクエストの場合
            elif data.get("type") == "text":
                user_message = data.get("text")
                print(f"【ユーザー】: {user_message}")
                
                response = chat.send_message(user_message, stream=True)
                
                sentence = ""
                for chunk in response:
                    if chunk.candidates and chunk.candidates[0].content.parts:
                        text_chunk = chunk.text
                        sentence += text_chunk
                        
                        if any(p in text_chunk for p in ["。", "！", "？", "\n"]):
                            clean_sentence = sentence.strip()
                            if clean_sentence:
                                print(f"【1文完成】: {clean_sentence}")
                                mp3_data = await generate_cloud_audio(clean_sentence, current_voice, current_rate, current_pitch)
                                if mp3_data:
                                    b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                                    await websocket.send_json({"type": "audio", "audio": b64_audio, "text": clean_sentence})
                            sentence = ""
                
                if sentence.strip():
                    mp3_data = await generate_cloud_audio(sentence.strip(), current_voice, current_rate, current_pitch)
                    if mp3_data:
                        b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                        await websocket.send_json({"type": "audio", "audio": b64_audio, "text": sentence.strip()})
                
                await websocket.send_json({"type": "end"})
            
    except Exception as e:
        print(f"【サーバー側】切断されました: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)