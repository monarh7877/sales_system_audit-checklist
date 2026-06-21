"""
Простой веб-сервер для раздачи статической страницы чек-листа.
Использует встроенный http.server — никаких внешних зависимостей не нужно.

Railway передаёт порт через переменную окружения PORT —
сервер слушает именно его.
"""

import os
import http.server
import socketserver

PORT = int(os.environ.get("PORT", 8000))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=".", **kwargs)


def main():
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Сервер запущен на порту {PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
