from flask import Flask, render_template_string
import pyautogui
import socket
import qrcode

app = Flask(__name__)

# HTML que o celular vai carregar
HTML_CONTROLE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Controle de Slides</title>
    <style>
        body { font-family: sans-serif; display: flex; flex-direction: column; height: 100vh; margin: 0; background: #121212; color: white; justify-content: center; align-items: center; }
        .btn { width: 80%; height: 35%; margin: 10px; border: none; border-radius: 20px; font-size: 24px; font-weight: bold; color: white; transition: transform 0.1s; }
        .next { background: #2ecc71; }
        .prev { background: #e74c3c; }
        .btn:active { transform: scale(0.95); opacity: 0.8; }
    </style>
</head>
<body>
    <button class="btn next" onclick="send('next')">PRÓXIMO ➔</button>
    <button class="btn prev" onclick="send('prev')">❮ ANTERIOR</button>

    <script>
        function send(cmd) {
            fetch('/' + cmd);
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_CONTROLE)

@app.route('/next')
def next_slide():
    pyautogui.press('right')
    return "ok"

@app.route('/prev')
def prev_slide():
    pyautogui.press('left')
    return "ok"

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

if __name__ == '__main__':
    meu_ip = get_ip()

    print("-" * 30)
    print(f"SERVIDOR INICIADO!")
    print(f"No seu celular, acesse: http://{meu_ip}:5000")
    print("-" * 30)

    url = f"http://{meu_ip}:5000"
    qr = qrcode.QRCode()
    qr.add_data(url)
    qr.print_ascii()
    
    app.run(host='0.0.0.0', port=5000)