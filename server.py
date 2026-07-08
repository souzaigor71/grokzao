import os
import json
import time
import asyncio
from flask import Flask, request, jsonify, render_template

from groq import Groq
import edge_tts

# ==================== CONFIGURAÇÕES ====================
# Defina a variável de ambiente antes de rodar:
#   Windows (PowerShell):  $env:GROQ_API_KEY="sua_key_aqui"
#   Termux/Linux:          export GROQ_API_KEY="sua_key_aqui"
API_KEY = os.environ.get("GROQ_API_KEY", "")
if not API_KEY:
    raise RuntimeError(
        "Defina a variável de ambiente GROQ_API_KEY antes de rodar o servidor.\n"
        "Windows (PowerShell): $env:GROQ_API_KEY=\"sua_key_aqui\"\n"
        "Termux/Linux: export GROQ_API_KEY=\"sua_key_aqui\""
    )

client = Groq(api_key=API_KEY)

MODELO = "llama-3.3-70b-versatile"
EDGE_TTS_VOZ = "pt-BR-AntonioNeural"

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

SYSTEM_PROMPT = (
    "Você é GrokZão, um robô humanoide brasileiro descontraído, sarcástico e inteligente. "
    "Fala naturalmente, como se estivesse conversando de verdade, sem parecer um assistente formal.\n\n"
    "Responda SEMPRE em JSON puro, sem markdown e sem texto fora do JSON, exatamente neste formato:\n"
    '{"resposta": "texto da resposta em português, natural e falado", '
    '"emocao": "neutro|feliz|sarcastico|surpreso|bravo"}\n\n'
    "A emoção deve refletir o tom real da resposta que você deu."
)

historico = [{"role": "system", "content": SYSTEM_PROMPT}]

app = Flask(__name__, template_folder=".")


def limpar_audios_antigos(max_idade_segundos: int = 300):
    agora = time.time()
    for nome in os.listdir(AUDIO_DIR):
        caminho = os.path.join(AUDIO_DIR, nome)
        if os.path.isfile(caminho) and agora - os.path.getmtime(caminho) > max_idade_segundos:
            try:
                os.remove(caminho)
            except OSError:
                pass


async def gerar_audio(texto: str, nome_arquivo: str) -> str:
    communicate = edge_tts.Communicate(text=texto, voice=EDGE_TTS_VOZ)
    caminho = os.path.join(AUDIO_DIR, nome_arquivo)
    await communicate.save(caminho)
    return caminho


def obter_resposta(texto_usuario: str):
    global historico
    historico.append({"role": "user", "content": texto_usuario})

    resp = client.chat.completions.create(
        model=MODELO,
        messages=historico,
        temperature=0.8,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    bruto = resp.choices[0].message.content.strip()

    try:
        dados = json.loads(bruto)
        resposta = dados.get("resposta", bruto)
        emocao = dados.get("emocao", "neutro")
        if emocao not in ("neutro", "feliz", "sarcastico", "surpreso", "bravo"):
            emocao = "neutro"
    except json.JSONDecodeError:
        resposta = bruto
        emocao = "neutro"

    historico.append({"role": "assistant", "content": bruto})

    # mantém o histórico enxuto (system + últimas 20 mensagens)
    if len(historico) > 21:
        historico[:] = [historico[0]] + historico[-20:]

    return resposta, emocao


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    dados = request.get_json(force=True, silent=True) or {}
    texto_usuario = (dados.get("mensagem") or "").strip()

    if not texto_usuario:
        return jsonify({"erro": "Mensagem vazia"}), 400

    try:
        resposta, emocao = obter_resposta(texto_usuario)
    except Exception as e:
        return jsonify({"erro": f"Erro ao consultar a IA: {e}"}), 500

    limpar_audios_antigos()
    nome_arquivo = f"fala_{int(time.time() * 1000)}.mp3"

    try:
        asyncio.run(gerar_audio(resposta, nome_arquivo))
        audio_url = f"/static/audio/{nome_arquivo}"
    except Exception as e:
        print(f"Erro na geração de voz: {e}")
        audio_url = None

    return jsonify({
        "resposta": resposta,
        "emocao": emocao,
        "audio_url": audio_url,
    })


@app.route("/reset", methods=["POST"])
def reset():
    global historico
    historico = [{"role": "system", "content": SYSTEM_PROMPT}]
    return jsonify({"ok": True})


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    print("🤖 GrokZão rodando!")
    print(f"   No mesmo dispositivo: http://localhost:{porta}")
    print(f"   De outro dispositivo na mesma rede Wi-Fi: http://SEU_IP_LOCAL:{porta}")
    app.run(host="0.0.0.0", port=porta, debug=False)
