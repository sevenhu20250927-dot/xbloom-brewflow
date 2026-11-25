"""Serve a private local menu, or add a bean or a guest to its order book."""
import argparse
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from threading import Lock
from urllib.parse import urlsplit

from . import providers, recommendations
from .store import Store, ProductError, daily_menu

WEB = Path(__file__).with_name("web")


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, mime="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        host = self.headers.get("Host", "")
        port = self.server.server_port
        if host not in (f"localhost:{port}", f"127.0.0.1:{port}"):
            raise ProductError(403, "仅接受本机地址")
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            raise ProductError(403, "请求来源不匹配")

    def do_GET(self):
        try:
            self.local_request()
            path = urlsplit(self.path).path
            files = {"/": ("index.html", "text/html"), "/menu": ("index.html", "text/html"),
                     "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            if path in files:
                name, mime = files[path]
                return self.respond(200, (WEB/name).read_bytes(), mime+"; charset=utf-8")
            if path == "/api/state":
                state = self.server.store.state()
                return self.respond(200, dict(state, menu=daily_menu(state["beans"]), provider=self.server.provider))
            self.respond(404, {"error": "未找到"})
        except ProductError as exc:
            self.respond(exc.status, {"error": str(exc)})

    def do_POST(self):
        try:
            self.local_request()
            if self.headers.get_content_type() != "application/json":
                raise ProductError(415, "请提交 JSON")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 32768:
                raise ProductError(413, "请求长度不正确")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ProductError(400, "请求必须是对象")
            store = self.server.store
            path = urlsplit(self.path).path
            if path == "/api/orders":
                result = store.create_order(data)
            elif match := re.fullmatch(r"/api/orders/([1-9][0-9]*)/(accept|finish|update|cancel|delete)", path):
                order_id, action = int(match[1]), match[2]
                result = store.update_order(order_id, data) if action == "update" else store.transition(order_id, data, action)
            elif path == "/api/preferences":
                result = store.save_preference(data)
            elif path == "/api/recommend" and set(data) == {"person_id"}:
                provider = self.server.provider
                if not provider:
                    raise ProductError(409, "启动时可通过 --recommend-with 和 --model 开启 AI 推荐")
                if not self.server.model_lock.acquire(blocking=False):
                    raise ProductError(409, "已有推荐正在生成")
                try:
                    ctx = recommendations.build_context(store.state(), person_id=data["person_id"])
                    if not ctx["candidates"]:
                        result = {"person_id": data["person_id"], "items": []}
                    else:
                        call = providers.call_codex if provider == "codex" else providers.call_deepseek
                        result = call(ctx, model=self.server.model)
                finally:
                    self.server.model_lock.release()
            else:
                raise ProductError(404, "未找到")
            self.respond(200, result)
        except ProductError as exc:
            self.respond(exc.status, {"error": str(exc)})
        except providers.AiPlanningError as exc:
            self.respond(502, {"error": str(exc)})
        except (UnicodeError, ValueError, RecursionError):
            self.respond(400, {"error": "资料格式不正确，请核对输入"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path.home()/".xbloom-brewflow"/"orders.sqlite3")
    sub = parser.add_subparsers(dest="cmd", required=True)
    person = sub.add_parser("add-person")
    person.add_argument("name")
    bean = sub.add_parser("add-bean")
    bean.add_argument("name")
    bean.add_argument("--grams", required=True, type=float)
    for field in ("roaster", "country", "process", "variety", "flavor", "notes"):
        bean.add_argument("--"+field, default="")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8770)
    serve.add_argument("--recommend-with", choices=("codex", "deepseek"))
    serve.add_argument("--model")
    args = parser.parse_args()
    store = Store(args.db)
    if args.cmd == "serve":
        if bool(args.recommend_with) != bool(args.model):
            parser.error("--recommend-with 与 --model 须一起提供")
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as http:
            http.store, http.provider, http.model = store, args.recommend_with, args.model
            http.model_lock = Lock()
            print(f"点单台 http://127.0.0.1:{http.server_port}/menu", flush=True)
            http.serve_forever()
    else:
        if not args.name.strip():
            parser.error("名称不能为空")
        with store._connection(write=True) as db:
            if args.cmd == "add-person":
                db.execute("INSERT INTO tasters(name) VALUES(?) ON CONFLICT(name) DO NOTHING", (args.name.strip(),))
            else:
                if not math.isfinite(args.grams) or args.grams < 0:
                    parser.error("余量必须是非负数")
                db.execute("""INSERT INTO menu_beans(name,roaster,country,process,variety_name,source_flavor,source_notes,net_weight)
                              VALUES(?,?,?,?,?,?,?,?)""", (args.name.strip(),args.roaster,args.country,args.process,
                                                         args.variety,args.flavor,args.notes,args.grams))


if __name__ == "__main__":
    main()
