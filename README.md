# GrokZão — Avatar Virtual

Avatar animado (rosto estilizado) que conversa usando a IA da Groq e fala em
português com `edge-tts`. Roda num servidor local (Flask) e você acessa pelo
navegador — funciona tanto no PC quanto no celular.

## ⚠️ Antes de tudo: troque sua API key

A key que estava no arquivo original ficou exposta. Gere uma nova em
https://console.groq.com/keys e revogue a antiga.

## 1. Instalar dependências

**Windows:**
```
py -m pip install -r requirements.txt
```

**Termux (Android):**
```
pkg install python
pip install -r requirements.txt
```

## 2. Definir a API key (variável de ambiente)

**Windows (PowerShell), toda vez que abrir um terminal novo:**
```
$env:GROQ_API_KEY="sua_key_aqui"
```

**Termux/Linux:**
```
export GROQ_API_KEY="sua_key_aqui"
```

Dica: para não digitar isso toda vez, você pode adicionar a linha `export ...`
no final do arquivo `~/.bashrc` (Termux) ou criar um atalho `.bat` no Windows
que define a variável antes de rodar o servidor.

## 3. Rodar o servidor

**Windows:**
```
py server.py
```

**Termux:**
```
python server.py
```

## 4. Abrir o avatar

- No mesmo dispositivo: abra `http://localhost:5000` no navegador.
- Do celular acessando o PC (ou vice-versa) na mesma rede Wi-Fi: descubra o
  IP local da máquina que está rodando o servidor (`ipconfig` no Windows,
  `ifconfig` no Termux) e acesse `http://SEU_IP_LOCAL:5000` no outro
  dispositivo.

## Como funciona

- `server.py`: recebe sua mensagem, manda pro modelo `llama-3.3-70b-versatile`
  da Groq pedindo uma resposta em JSON com o texto e uma "emoção"
  (`neutro`, `feliz`, `sarcastico`, `surpreso`, `bravo`), gera o áudio com
  `edge-tts` e devolve tudo pro navegador.
- `templates/index.html`: desenha o rosto (CSS puro, sem imagens externas —
  fácil de estilizar), pisca os olhos sozinho, troca de expressão conforme a
  emoção recebida, e mexe a boca em tempo real analisando o volume do áudio
  enquanto ele toca (Web Audio API).

## Próximos passos possíveis

- Trocar o rosto CSS por um modelo Live2D de verdade (biblioteca
  `pixi-live2d-display` no JS), se quiser algo mais parecido com VTuber.
- Adicionar entrada por voz (Web Speech API no navegador) em vez de só texto.
- Migrar o avatar pra Unity, usando o `server.py` como backend via
  requisições HTTP — o "cérebro" continua o mesmo.
- Quando quiser partir pro robô físico, dá pra reaproveitar o `server.py`
  quase inteiro: em vez de mandar a "emoção" pro navegador, ele manda
  comandos de servo pro ESP32.
