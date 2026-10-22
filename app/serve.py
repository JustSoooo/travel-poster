# -*- coding: utf-8 -*-
"""生产环境入口：waitress 多线程服务"""
import os
from waitress import serve
import db
from server import app

if __name__ == "__main__":
    db.connect().close()
    port = int(os.environ.get("PORT", 8090))
    print(f"旅行海报已启动：在浏览器打开 http://<NAS 的 IP>:{port}", flush=True)
    serve(app, host="0.0.0.0", port=port, threads=8)
